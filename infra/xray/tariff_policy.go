package dispatcher

// Rovyn's policy is opt-in and local to a single node. All authenticated
// credentials in a subscription share one limiter and one durable quota.
import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/buf"
	"github.com/xtls/xray-core/common/protocol"
	"golang.org/x/time/rate"
)

const tariffBurst = 65536
const quotaReservation = 4 * 1024 * 1024

var errTariff = errors.New("subscription traffic policy denied transfer")

type tariffRule struct {
	ID     string   `json:"id"`
	Emails []string `json:"emails"`
	Mbps   int64    `json:"mbps"`
	Quota  int64    `json:"quota"`
	FUP    bool     `json:"fup"`
}
type tariffDocument struct {
	Version int          `json:"version"`
	Groups  []tariffRule `json:"groups"`
}
type tariffBucket struct {
	Second int64 `json:"second"`
	Bytes  int64 `json:"bytes"`
}
type tariffState struct {
	Reserved  int64             `json:"reserved"`
	Started   int64             `json:"started"`
	Throttled bool              `json:"throttled"`
	LowSince  int64             `json:"low_since"`
	Buckets   [600]tariffBucket `json:"buckets"`
}
type tariffGroup struct {
	Rule     tariffRule
	State    tariffState
	Used     int64
	Up, Down *rate.Limiter
	Current  rate.Limit
}
type tariffManager struct {
	sync.Mutex
	path    string
	groups  map[string]*tariffGroup
	emails  map[string]string
	states  map[string]tariffState
	healthy bool
	digest  string
	// Cache only a checkpoint that completed both file and directory fsync.
	persistedState []byte
}

var tariffOnce sync.Once
var tariffs *tariffManager

func localTariffs() *tariffManager {
	tariffOnce.Do(func() {
		path := os.Getenv("XRAY_ROVYN_TARIFF_POLICY")
		if path == "" {
			return
		}
		m := &tariffManager{path: path, groups: map[string]*tariffGroup{}, emails: map[string]string{}, states: map[string]tariffState{}}
		// The deployment creates an empty state file before first activation.
		data, err := os.ReadFile(path + ".state")
		m.healthy = err == nil && json.Unmarshal(data, &m.states) == nil && m.states != nil
		if m.healthy {
			m.persistedState = bytes.Clone(data)
		}
		m.reload()
		tariffs = m
		go func() {
			for range time.Tick(time.Second) {
				m.Lock()
				m.reload()
				for _, g := range m.groups {
					g.evaluate(time.Now().Unix())
				}
				if m.healthy {
					if err := m.persist(); err != nil {
						m.healthy = false
					}
				}
				m.acknowledge()
				m.Unlock()
			}
		}()
	})
	return tariffs
}

// Caller holds the manager lock after initialization. Invalid updates retain the
// last known policy; a missing initial policy denies every authenticated user.
func (m *tariffManager) reload() {
	data, err := os.ReadFile(m.path)
	if err != nil {
		return
	}
	var doc tariffDocument
	if json.Unmarshal(data, &doc) != nil || doc.Version != 1 {
		return
	}
	emails := map[string]string{}
	rules := map[string]tariffRule{}
	for _, r := range doc.Groups {
		if r.ID == "" || r.Mbps < 0 || r.Quota < 0 {
			return
		}
		if _, exists := rules[r.ID]; exists {
			return
		}
		rules[r.ID] = r
		for _, email := range r.Emails {
			if email == "" || emails[email] != "" {
				return
			}
			emails[email] = r.ID
		}
	}
	for id, r := range rules {
		g := m.groups[id]
		if g == nil {
			s := m.states[id]
			g = &tariffGroup{State: s, Used: s.Reserved, Up: rate.NewLimiter(rate.Inf, tariffBurst), Down: rate.NewLimiter(rate.Inf, tariffBurst), Current: rate.Inf}
			m.groups[id] = g
		}
		g.Rule = r
		g.evaluate(time.Now().Unix())
	}
	for id := range m.groups {
		if _, exists := rules[id]; !exists {
			delete(m.groups, id)
		}
	}
	m.emails = emails
	digest := sha256.Sum256(data)
	m.digest = hex.EncodeToString(digest[:])
}

func (m *tariffManager) acknowledge() {
	usage := map[string]int64{}
	for id, g := range m.groups {
		if g.Rule.Quota > 0 {
			usage[id] = g.Used
		}
	}
	data, err := json.Marshal(map[string]interface{}{"digest": m.digest, "healthy": m.healthy, "checked_at": time.Now().Unix(), "usage": usage})
	if err != nil {
		return
	}
	f, err := os.CreateTemp(filepath.Dir(m.path), ".tariff-applied-*")
	if err != nil {
		return
	}
	defer os.Remove(f.Name())
	_, err = f.Write(data)
	if f.Close() != nil || err != nil {
		return
	}
	_ = os.Rename(f.Name(), m.path+".applied")
}

func (g *tariffGroup) evaluate(now int64) {
	var window, recent int64
	for _, b := range g.State.Buckets {
		if b.Second > now-600 && b.Second <= now {
			window += b.Bytes
		}
		if b.Second > now-60 && b.Second <= now {
			recent += b.Bytes
		}
	}
	if g.Rule.FUP {
		if !g.State.Throttled && g.State.Started > 0 && now-g.State.Started >= 600 && window > 12_500_000*600 {
			g.State.Throttled = true
		}
		if g.State.Throttled {
			// Low load is a rolling minute averaging below 10 Mbit/s.
			if recent < 1_250_000*60 {
				if g.State.LowSince == 0 {
					g.State.LowSince = now
				}
				if now-g.State.LowSince >= 900 {
					g.State.Throttled = false
					g.State.LowSince = 0
				}
			} else {
				g.State.LowSince = 0
			}
		}
	}
	limit := rate.Inf
	if g.Rule.Mbps > 0 {
		limit = rate.Limit(g.Rule.Mbps * 1_000_000 / 8)
	}
	if g.Rule.FUP && g.State.Throttled {
		limit = rate.Limit(12_500_000)
	}
	if limit != g.Current {
		g.Up.SetLimit(limit)
		g.Down.SetLimit(limit)
		g.Current = limit
		// Prevent the unlimited phase from leaving an unlimited token balance.
		if limit != rate.Inf {
			g.Up.AllowN(time.Now(), tariffBurst)
			g.Down.AllowN(time.Now(), tariffBurst)
		}
	}
}

func (m *tariffManager) persist() error {
	for id, g := range m.groups {
		if g.Rule.Quota > 0 || g.Rule.FUP {
			m.states[id] = g.State
		}
	}
	data, err := json.Marshal(m.states)
	if err != nil {
		return err
	}
	// The timer also runs when every user is unlimited and no FUP bucket has
	// changed. Do not fsync an identical historical checkpoint under the global
	// traffic mutex: slow storage would stall unrelated live TCP/UDP transfers.
	if bytes.Equal(data, m.persistedState) {
		return nil
	}
	f, err := os.CreateTemp(filepath.Dir(m.path), ".tariff-state-*")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Rename(name, m.path+".state"); err != nil {
		return err
	}
	dir, err := os.Open(filepath.Dir(m.path))
	if err != nil {
		return err
	}
	defer dir.Close()
	if err = dir.Sync(); err != nil {
		return err
	}
	m.persistedState = data
	return nil
}

func (m *tariffManager) take(ctx context.Context, email string, size int, down bool) error {
	m.Lock()
	g := m.groups[m.emails[email]]
	if !m.healthy || g == nil {
		m.Unlock()
		return errTariff
	}
	if g.Rule.Quota > 0 {
		if g.Used+int64(size) > g.Rule.Quota {
			// A complete UDP datagram/TLS buffer cannot be split safely here.
			// Close the group at the boundary rather than letting reconnects use
			// a small leftover quota after a large transfer has been stopped.
			g.Used = g.Rule.Quota
			if g.State.Reserved < g.Rule.Quota {
				g.State.Reserved = g.Rule.Quota
				if err := m.persist(); err != nil {
					m.healthy = false
				}
			}
			m.Unlock()
			return errTariff
		}
		if g.Used+int64(size) > g.State.Reserved {
			g.State.Reserved = min(g.Rule.Quota, g.Used+max(quotaReservation, int64(size)))
			if err := m.persist(); err != nil {
				m.healthy = false
				m.Unlock()
				return errTariff
			}
		}
		g.Used += int64(size)
	}
	g.evaluate(time.Now().Unix())
	limiter := g.Up
	if down {
		limiter = g.Down
	}
	m.Unlock()
	for size > 0 {
		n := min(size, tariffBurst)
		if err := limiter.WaitN(ctx, n); err != nil {
			return err
		}
		size -= n
	}
	return nil
}

func (m *tariffManager) delivered(email string, size int) {
	m.Lock()
	defer m.Unlock()
	g := m.groups[m.emails[email]]
	if g == nil || !g.Rule.FUP {
		return
	}
	now := time.Now().Unix()
	if g.State.Started == 0 {
		g.State.Started = now
	}
	b := &g.State.Buckets[now%600]
	if b.Second != now {
		*b = tariffBucket{Second: now}
	}
	b.Bytes += int64(size)
	g.evaluate(now)
}

func tariffContext(ctx context.Context, user *protocol.MemoryUser) (context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(ctx)
	go func() {
		select {
		case <-user.Revoked():
			cancel()
		case <-ctx.Done():
		}
	}()
	return ctx, cancel
}

type tariffWriter struct {
	Writer buf.Writer
	ctx    context.Context
	user   *protocol.MemoryUser
	m      *tariffManager
	down   bool
	cancel context.CancelFunc
}

func newTariffWriter(ctx context.Context, user *protocol.MemoryUser, m *tariffManager, writer buf.Writer, down bool) *tariffWriter {
	ctx, cancel := tariffContext(ctx, user)
	return &tariffWriter{Writer: writer, ctx: ctx, user: user, m: m, down: down, cancel: cancel}
}
func (w *tariffWriter) WriteMultiBuffer(mb buf.MultiBuffer) error {
	// Keep individual UDP buffers intact. Large TCP batches must not produce a
	// burst proportional to the number of simultaneous connections.
	for i, b := range mb {
		select {
		case <-w.user.Revoked():
			buf.ReleaseMulti(mb[i:])
			return errTariff
		default:
		}
		size := int(b.Len())
		if err := w.m.take(w.ctx, w.user.Email, size, w.down); err != nil {
			buf.ReleaseMulti(mb[i:])
			return err
		}
		select {
		case <-w.user.Revoked():
			buf.ReleaseMulti(mb[i:])
			return errTariff
		case <-w.ctx.Done():
			buf.ReleaseMulti(mb[i:])
			return w.ctx.Err()
		default:
		}
		if err := w.Writer.WriteMultiBuffer(buf.MultiBuffer{b}); err != nil {
			buf.ReleaseMulti(mb[i+1:])
			return err
		}
		if w.down {
			w.m.delivered(w.user.Email, size)
		}
	}
	return nil
}
func (w *tariffWriter) Close() error { w.cancel(); return common.Close(w.Writer) }
func (w *tariffWriter) Interrupt()   { w.cancel(); common.Interrupt(w.Writer) }

type tariffReader struct {
	Reader  buf.Reader
	ctx     context.Context
	user    *protocol.MemoryUser
	m       *tariffManager
	cancel  context.CancelFunc
	mu      sync.Mutex
	pending buf.MultiBuffer
	err     error
}

func newTariffReader(ctx context.Context, user *protocol.MemoryUser, m *tariffManager, reader buf.Reader) *tariffReader {
	ctx, cancel := tariffContext(ctx, user)
	return &tariffReader{Reader: reader, ctx: ctx, user: user, m: m, cancel: cancel}
}
func (r *tariffReader) ReadMultiBuffer() (buf.MultiBuffer, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.pending) == 0 {
		r.pending, r.err = r.Reader.ReadMultiBuffer()
	}
	if len(r.pending) == 0 {
		return nil, r.err
	}
	b := r.pending[0]
	err := r.m.take(r.ctx, r.user.Email, int(b.Len()), false)
	select {
	case <-r.user.Revoked():
		err = errTariff
	default:
	}
	if err == nil {
		err = r.ctx.Err()
	}
	if err != nil {
		buf.ReleaseMulti(r.pending)
		r.pending = nil
		return nil, err
	}
	r.pending = r.pending[1:]
	if len(r.pending) == 0 {
		return buf.MultiBuffer{b}, r.err
	}
	return buf.MultiBuffer{b}, nil
}
func (r *tariffReader) Interrupt() {
	r.cancel()
	common.Interrupt(r.Reader)
	r.mu.Lock()
	defer r.mu.Unlock()
	buf.ReleaseMulti(r.pending)
	r.pending = nil
}
func (r *tariffReader) Close() error { r.Interrupt(); return common.Close(r.Reader) }

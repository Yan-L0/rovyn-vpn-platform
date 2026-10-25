package dispatcher

import (
	"context"
	"encoding/json"
	"github.com/xtls/xray-core/common/buf"
	"github.com/xtls/xray-core/common/protocol"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"golang.org/x/time/rate"
)

func testTariffs(t *testing.T, quota, mbps int64) *tariffManager {
	t.Helper()
	path := filepath.Join(t.TempDir(), "policy.json")
	doc, _ := json.Marshal(tariffDocument{Version: 1, Groups: []tariffRule{{ID: "subscription", Emails: []string{"phone", "tv"}, Quota: quota, Mbps: mbps}}})
	if err := os.WriteFile(path, doc, 0600); err != nil {
		t.Fatal(err)
	}
	m := &tariffManager{path: path, groups: map[string]*tariffGroup{}, emails: map[string]string{}, states: map[string]tariffState{}, healthy: true}
	m.reload()
	return m
}

func TestTariffQuotaSharedAcrossDevicesAndDirections(t *testing.T) {
	m := testTariffs(t, 300, 0)
	if err := m.take(context.Background(), "phone", 100, false); err != nil {
		t.Fatal(err)
	}
	if err := m.take(context.Background(), "tv", 200, true); err != nil {
		t.Fatal(err)
	}
	if err := m.take(context.Background(), "phone", 1, true); err == nil {
		t.Fatal("quota bypassed")
	}
	if err := m.take(context.Background(), "unknown", 1, true); err == nil {
		t.Fatal("unknown identity permitted")
	}
}

func TestTariffQuotaBoundaryClosesEveryDevice(t *testing.T) {
	m := testTariffs(t, 300, 0)
	if err := m.take(context.Background(), "phone", 290, true); err != nil {
		t.Fatal(err)
	}
	if m.take(context.Background(), "phone", 32, true) == nil {
		t.Fatal("oversized datagram permitted")
	}
	if m.take(context.Background(), "tv", 1, false) == nil {
		t.Fatal("other device reused exhausted quota tail")
	}
}

func TestTariffQuotaSurvivesRestartAndPolicyReload(t *testing.T) {
	m := testTariffs(t, 300, 0)
	if err := m.take(context.Background(), "phone", 300, false); err != nil {
		t.Fatal(err)
	}
	m.reload()
	if err := m.take(context.Background(), "tv", 1, false); err == nil {
		t.Fatal("reload reset quota")
	}
	data, err := os.ReadFile(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	next := &tariffManager{path: m.path, groups: map[string]*tariffGroup{}, emails: map[string]string{}, states: map[string]tariffState{}, healthy: true}
	if err := json.Unmarshal(data, &next.states); err != nil {
		t.Fatal(err)
	}
	next.reload()
	if err := next.take(context.Background(), "tv", 1, true); err == nil {
		t.Fatal("restart reset quota")
	}
}

func TestTariffConcurrentDevicesCannotDoubleSpend(t *testing.T) {
	m := testTariffs(t, 1000, 0)
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _ = m.take(context.Background(), "tv", 100, true) }()
	}
	wg.Wait()
	if m.groups["subscription"].Used != 1000 {
		t.Fatal("concurrent accounting failed")
	}
}

func TestTariffFUPWindowAndAutomaticRecovery(t *testing.T) {
	g := &tariffGroup{Rule: tariffRule{FUP: true}, Up: rate.NewLimiter(rate.Inf, tariffBurst), Down: rate.NewLimiter(rate.Inf, tariffBurst), Current: rate.Inf}
	g.State.Started = 10000
	for s := int64(10001); s <= 10600; s++ {
		g.State.Buckets[s%600] = tariffBucket{Second: s, Bytes: 13_000_000}
	}
	g.evaluate(10599)
	if g.State.Throttled {
		t.Fatal("throttled before ten minutes")
	}
	g.evaluate(10600)
	if !g.State.Throttled || g.Current != rate.Limit(12_500_000) {
		t.Fatal("sustained load did not throttle")
	}
	g.evaluate(10661)
	if g.State.LowSince != 10661 {
		t.Fatal("low-load recovery did not start")
	}
	g.evaluate(11560)
	if !g.State.Throttled {
		t.Fatal("recovered before fifteen minutes")
	}
	g.evaluate(11561)
	if g.State.Throttled || g.Current != rate.Inf {
		t.Fatal("full speed not restored")
	}
}

func TestTariffAggregateRateAndCancellation(t *testing.T) {
	m := testTariffs(t, 0, 1)
	start := time.Now()
	var wg sync.WaitGroup
	for _, user := range []string{"phone", "tv"} {
		wg.Add(1)
		go func(email string) {
			defer wg.Done()
			for i := 0; i < 4; i++ {
				if err := m.take(context.Background(), email, tariffBurst, true); err != nil {
					t.Error(err)
				}
			}
		}(user)
	}
	wg.Wait()
	if time.Since(start) < 3*time.Second {
		t.Fatal("each device received a separate speed limit")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if err := m.take(ctx, "phone", tariffBurst, true); err == nil {
		t.Fatal("cancellation ignored")
	}
}

func TestTariffPersistenceFailureDeniesTraffic(t *testing.T) {
	m := testTariffs(t, 300, 0)
	m.path = filepath.Join(t.TempDir(), "missing", "policy.json")
	if m.take(context.Background(), "phone", 1, true) == nil || m.healthy {
		t.Fatal("storage failure silently reset or ignored")
	}
}

func TestTariffUnchangedCheckpointDoesNotTouchDisk(t *testing.T) {
	m := testTariffs(t, 0, 0)
	if err := m.persist(); err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 10; i++ {
		m.reload()
		if err := m.take(context.Background(), "phone", tariffBurst, true); err != nil {
			t.Fatal(err)
		}
		if err := m.persist(); err != nil {
			t.Fatal(err)
		}
		after, err := os.Stat(m.path + ".state")
		if err != nil {
			t.Fatal(err)
		}
		if !os.SameFile(before, after) {
			t.Fatal("unchanged unlimited traffic rewrote the checkpoint")
		}
	}
}

func TestTariffChangedReservationStillPersistsBeforeDelivery(t *testing.T) {
	m := testTariffs(t, 3*quotaReservation, 0)
	if err := m.take(context.Background(), "phone", 1, true); err != nil {
		t.Fatal(err)
	}
	first, err := os.Stat(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	if err := m.take(context.Background(), "tv", quotaReservation, false); err != nil {
		t.Fatal(err)
	}
	second, err := os.Stat(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]tariffState
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatal(err)
	}
	if os.SameFile(first, second) || state["subscription"].Reserved < quotaReservation+1 {
		t.Fatal("changed quota reservation was not durably checkpointed")
	}
	// A prior successful checkpoint must not mask a subsequent storage error.
	m.path = filepath.Join(t.TempDir(), "missing", "policy.json")
	if m.take(context.Background(), "phone", quotaReservation, false) == nil || m.healthy {
		t.Fatal("new reservation bypassed a persistence failure")
	}
}

func TestTariffChangedFUPBucketIsCheckpointed(t *testing.T) {
	m := testTariffs(t, 0, 0)
	m.groups["subscription"].Rule.FUP = true
	if err := m.persist(); err != nil {
		t.Fatal(err)
	}
	m.delivered("phone", 1234)
	if err := m.persist(); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(m.path + ".state")
	if err != nil {
		t.Fatal(err)
	}
	var state map[string]tariffState
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatal(err)
	}
	var delivered int64
	for _, b := range state["subscription"].Buckets {
		delivered += b.Bytes
	}
	if delivered != 1234 {
		t.Fatal("checkpoint cache lost changed FUP accounting")
	}
}

type tariffSink struct{ Writes int }

func (s *tariffSink) WriteMultiBuffer(mb buf.MultiBuffer) error {
	s.Writes++
	buf.ReleaseMulti(mb)
	return nil
}

func TestTariffRevocationInterruptsQueuedDownload(t *testing.T) {
	m := testTariffs(t, 0, 1)
	g := m.groups["subscription"]
	g.Current = rate.Limit(0.000008)
	g.Rule.Mbps = 0
	g.Rule.FUP = false
	// Keep an intentionally long queue, without changing production timing.
	g.Down = rate.NewLimiter(rate.Limit(1), tariffBurst)
	g.Down.AllowN(time.Now(), tariffBurst)
	g.Current = rate.Inf
	u := &protocol.MemoryUser{Email: "phone"}
	sink := &tariffSink{}
	w := newTariffWriter(context.Background(), u, m, sink, true)
	defer w.Close()
	b := buf.New()
	b.Write([]byte("queued data"))
	done := make(chan error, 1)
	go func() { done <- w.WriteMultiBuffer(buf.MultiBuffer{b}) }()
	time.Sleep(20 * time.Millisecond)
	u.Revoke()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("revoked write succeeded")
		}
	case <-time.After(250 * time.Millisecond):
		t.Fatal("revocation left queued traffic alive")
	}
	if sink.Writes != 0 {
		t.Fatal("revoked data reached downstream writer")
	}
}

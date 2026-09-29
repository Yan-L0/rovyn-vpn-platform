package protocol

import (
	"sync"
	"testing"
)

func TestRevokeIsGenerationScopedAndConcurrent(t *testing.T) {
	old := &MemoryUser{Email: "same"}
	replacement := &MemoryUser{Email: "same"}
	other := &MemoryUser{Email: "other"}
	var workers sync.WaitGroup
	for i := 0; i < 100; i++ {
		workers.Add(1)
		go func() { defer workers.Done(); old.Revoked(); old.Revoke() }()
	}
	workers.Wait()
	select {
	case <-old.Revoked():
	default:
		t.Fatal("old user remains authorized")
	}
	for _, user := range []*MemoryUser{replacement, other} {
		select {
		case <-user.Revoked():
			t.Fatal("unrelated generation revoked")
		default:
		}
	}
}

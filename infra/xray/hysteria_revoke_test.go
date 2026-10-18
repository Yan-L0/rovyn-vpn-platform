package account

import (
	"testing"

	"github.com/xtls/xray-core/common/protocol"
)

func TestRouteViewRevokedWithCanonicalCredential(t *testing.T) {
	const auth = "00000000-0000-4000-8000-000000000001"
	const routedAuth = "00000000-0000-4001-8000-000000000001"
	v := NewValidator()
	u := &protocol.MemoryUser{Email: "device", Account: &MemoryAccount{Auth: auth}}
	if err := v.Add(u); err != nil {
		t.Fatal(err)
	}
	view := v.Get(routedAuth)
	if view == nil || view == u || view.Revoked() != u.Revoked() {
		t.Fatal("route view must share the canonical credential generation")
	}
	if err := v.DelByEmail(u.Email); err != nil {
		t.Fatal(err)
	}
	select {
	case <-view.Revoked():
	default:
		t.Fatal("deleted credential's route view remains authorized")
	}
	if v.Get(routedAuth) != nil {
		t.Fatal("deleted credential can authenticate")
	}
	replacement := &protocol.MemoryUser{Email: u.Email, Account: &MemoryAccount{Auth: auth}}
	if err := v.Add(replacement); err != nil {
		t.Fatal(err)
	}
	select {
	case <-v.Get(routedAuth).Revoked():
		t.Fatal("replacement generation inherited revocation")
	default:
	}
}

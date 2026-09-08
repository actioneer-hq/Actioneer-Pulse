package main

import (
	"net/http"
	"testing"
	"time"

	"github.com/alexedwards/argon2id"
)

func TestSanitizeSlugAndSchema(t *testing.T) {
	cases := map[string]string{
		"default":   "t_default",
		"vastu-hfc": "t_vastu_hfc",
		"Acme Co.":  "t_acme_co_",
		"":          "t_default",
	}
	for in, want := range cases {
		if got := schemaName(in); got != want {
			t.Errorf("schemaName(%q): want %q, got %q", in, want, got)
		}
	}
}

func TestTokenPrefix(t *testing.T) {
	if p, ok := tokenPrefix("vo_deadbeef_secret"); !ok || p != "deadbeef" {
		t.Errorf("want (deadbeef,true), got (%q,%v)", p, ok)
	}
	for _, bad := range []string{"", "nope", "vo_", "vo_onlyprefix", "bearer x"} {
		if _, ok := tokenPrefix(bad); ok {
			t.Errorf("tokenPrefix(%q) should be invalid", bad)
		}
	}
}

// TestArgon2CrossLanguage verifies a hash produced by the Python argon2-cffi PasswordHasher (the
// production hasher) against the Go verifier — the two must agree or tokens won't authenticate.
func TestArgon2CrossLanguage(t *testing.T) {
	const (
		token = "vo_deadbeef_supersecretvalue123"
		hash  = "$argon2id$v=19$m=65536,t=3,p=4$3D69VGNkKeq5GmKrYkqttQ$IsUEmR/xNVX6zO06qhYMKUbmhL/OS56J/QqfXKThceg"
	)
	ok, err := argon2id.ComparePasswordAndHash(token, hash)
	if err != nil {
		t.Fatalf("compare error: %v", err)
	}
	if !ok {
		t.Fatal("Go failed to verify a Python-generated argon2id hash — cross-language mismatch")
	}
	bad, _ := argon2id.ComparePasswordAndHash("vo_deadbeef_wrong", hash)
	if bad {
		t.Fatal("wrong token verified against the hash")
	}
}

func TestDevOpenAuthIdentity(t *testing.T) {
	h := http.Header{}
	h.Set(orgHeader, "vastu-hfc")
	id, err := devOpenAuth{}.identify(t.Context(), h)
	if err != nil {
		t.Fatal(err)
	}
	if id.org != "vastu-hfc" || id.agentID != "" {
		t.Errorf("dev-open identity: got %+v", id)
	}
	// no org header -> default
	id2, _ := devOpenAuth{}.identify(t.Context(), http.Header{})
	if id2.org != "default" {
		t.Errorf("default org: got %q", id2.org)
	}
}

func TestTokenFromHeaders(t *testing.T) {
	h := http.Header{}
	h.Set("Authorization", "Bearer vo_a_b")
	if got := tokenFromHeaders(h); got != "vo_a_b" {
		t.Errorf("bearer: got %q", got)
	}
	h2 := http.Header{}
	h2.Set("X-Voiceobs-Token", "vo_c_d")
	if got := tokenFromHeaders(h2); got != "vo_c_d" {
		t.Errorf("x-token: got %q", got)
	}
}

func TestTokenCacheLRUAndTTL(t *testing.T) {
	c := newTokenCache(2, time.Minute)
	fake := time.Unix(0, 0)
	c.nowF = func() time.Time { return fake }

	c.put("k1", identity{org: "o1"})
	c.put("k2", identity{org: "o2"})
	if _, ok := c.get("k1"); !ok {
		t.Fatal("k1 should be present")
	}
	// insert k3 -> evicts LRU (k2, since k1 was just touched)
	c.put("k3", identity{org: "o3"})
	if _, ok := c.get("k2"); ok {
		t.Error("k2 should have been evicted")
	}
	if _, ok := c.get("k1"); !ok {
		t.Error("k1 should survive (recently used)")
	}
	// expiry
	fake = fake.Add(2 * time.Minute)
	if _, ok := c.get("k1"); ok {
		t.Error("k1 should be expired")
	}
}

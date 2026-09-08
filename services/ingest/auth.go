package main

import (
	"context"
	"net/http"
	"strings"
)

const orgHeader = "X-Voiceobs-Org"

// authErr is a token-auth failure -> HTTP 401. Mirrors ingest_identity's HTTPException(401).
type authErr struct{ msg string }

func (e authErr) Error() string { return e.msg }

// identity is who a producer authenticated as: the org slug (schema) and the agent id (may be "").
type identity struct {
	org     string
	agentID string
}

// authenticator resolves a request's identity. P2 adds the Postgres/argon2 implementation; P0/dev
// uses devOpenAuth.
type authenticator interface {
	identify(ctx context.Context, h http.Header) (identity, error)
}

// tokenFromHeaders extracts the ingest token from Authorization: Bearer <t> or X-Voiceobs-Token.
func tokenFromHeaders(h http.Header) string {
	if a := h.Get("Authorization"); len(a) >= 7 && strings.EqualFold(a[:7], "bearer ") {
		return strings.TrimSpace(a[7:])
	}
	return h.Get("X-Voiceobs-Token")
}

func orgFromHeaders(h http.Header) string {
	if o := h.Get(orgHeader); o != "" {
		return o
	}
	return "default"
}

// devOpenAuth allows token-less ingest: identity is (org-from-header, ""). Used under dev-open, where
// the Python side returns (None, None). A token, if present, is ignored here (no DB in dev).
type devOpenAuth struct{}

func (devOpenAuth) identify(_ context.Context, h http.Header) (identity, error) {
	return identity{org: orgFromHeaders(h), agentID: ""}, nil
}

package main

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/alexedwards/argon2id"
	"github.com/jackc/pgx/v5/pgxpool"
)

// pgAuth is the production authenticator: it validates an ingest token against the ingest_token table
// in the request's org schema, argon2id-verifying the full vo_<prefix>_<secret> plaintext. Mirrors
// resolve_ingest_token + ingest_identity. No token (and not dev-open) -> 401.
type pgAuth struct {
	pool  *pgxpool.Pool
	cache *tokenCache
}

func newPGAuth(ctx context.Context, dsn string) (*pgAuth, error) {
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		return nil, err
	}
	return &pgAuth{pool: pool, cache: newTokenCache(4096, 5*time.Minute)}, nil
}

func (a *pgAuth) identify(ctx context.Context, h http.Header) (identity, error) {
	org := orgFromHeaders(h)
	token := tokenFromHeaders(h)
	if token == "" {
		return identity{}, authErr{"ingest token required"}
	}
	// Kafka org is the header org (matching the Python endpoint, which passes x_org, not the token's
	// org); the token only supplies the agent id and confirms access within this schema.
	cacheKey := org + "\x00" + token
	if id, ok := a.cache.get(cacheKey); ok {
		return id, nil
	}

	prefix, ok := tokenPrefix(token)
	if !ok {
		return identity{}, authErr{"invalid ingest token"}
	}

	agentID, matched, err := a.verify(ctx, org, prefix, token)
	if err != nil {
		return identity{}, err // infra error -> 500 upstream
	}
	if !matched {
		return identity{}, authErr{"invalid ingest token"}
	}
	id := identity{org: org, agentID: agentID}
	a.cache.put(cacheKey, id)
	return id, nil
}

// verify pins the org schema on one connection and argon2id-checks the token against every live row
// with the matching prefix. Returns the agent id on the first match.
func (a *pgAuth) verify(ctx context.Context, org, prefix, token string) (agentID string, matched bool, err error) {
	conn, err := a.pool.Acquire(ctx)
	if err != nil {
		return "", false, err
	}
	defer conn.Release()

	// search_path must be SET on the same connection as the query. schemaName is sanitized to
	// [a-z0-9_], so the quoted identifier interpolation is safe.
	if _, err := conn.Exec(ctx, fmt.Sprintf(`SET search_path TO %q`, schemaName(org))); err != nil {
		return "", false, err
	}
	rows, err := conn.Query(ctx,
		`SELECT agent_id, token_hash FROM ingest_token WHERE token_prefix = $1 AND revoked_at IS NULL`,
		prefix)
	if err != nil {
		return "", false, err
	}
	defer rows.Close()
	for rows.Next() {
		var aid, hash string
		if err := rows.Scan(&aid, &hash); err != nil {
			return "", false, err
		}
		ok, err := argon2id.ComparePasswordAndHash(token, hash)
		if err != nil {
			continue // malformed hash — skip, matching Python's InvalidHashError continue
		}
		if ok {
			return aid, true, rows.Err()
		}
	}
	return "", false, rows.Err()
}

func (a *pgAuth) Close() { a.pool.Close() }

// tokenPrefix extracts the prefix from a vo_<prefix>_<secret> token, matching resolve_ingest_token.
func tokenPrefix(token string) (string, bool) {
	if !strings.HasPrefix(token, "vo_") {
		return "", false
	}
	parts := strings.SplitN(token, "_", 3)
	if len(parts) < 3 || parts[1] == "" {
		return "", false
	}
	return parts[1], true
}

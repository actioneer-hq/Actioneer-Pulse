package main

import (
	"crypto/rand"
	"encoding/hex"
	"strconv"
	"time"
)

// newBatchID returns 32 lowercase hex chars (no dashes), matching Python's uuid4().hex.
func newBatchID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

// isoMicros renders t like Python's datetime.now(UTC).isoformat(): microsecond precision with a
// +00:00 offset, e.g. 2026-09-08T12:34:56.789012+00:00.
func isoMicros(t time.Time) string {
	return t.UTC().Format("2006-01-02T15:04:05.000000-07:00")
}

func itoa(i int) string { return strconv.Itoa(i) }

package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

// goldenFile is the Python-produced reference: regenerate with
//
//	uv run python services/ingest/testdata/gen_golden.py
type goldenFile struct {
	Org     string         `json:"org"`
	AgentID string         `json:"agent_id"`
	Topic   string         `json:"topic"`
	Payload map[string]any `json:"payload"`
	Records []goldenRecord `json:"records"`
}

type goldenRecord struct {
	Key     string            `json:"key"`
	Headers map[string]string `json:"headers"`
	Value   map[string]any    `json:"value"`
}

// TestGoldenParity feeds the exact fixture the Python produce() ran through the Go pipeline and asserts
// the records match byte-for-contract: same count/order, same key, same stable headers, and the same
// decompressed JSON value. batch_id and received_at are per-run, so they're checked for presence only.
func TestGoldenParity(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("testdata", "records.json"))
	if err != nil {
		t.Fatalf("read golden (regenerate with gen_golden.py): %v", err)
	}
	var g goldenFile
	if err := json.Unmarshal(raw, &g); err != nil {
		t.Fatal(err)
	}

	// Fixed batchID/time — the Go values differ per run, so equality ignores those two headers.
	got, err := buildRecords(g.Payload, g.Org, g.AgentID, "goldenbatch", time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != len(g.Records) {
		t.Fatalf("record count: want %d, got %d", len(g.Records), len(got))
	}

	stable := []string{"org", "agent_id", "shard_key", "trace_id", "seq"}
	for i, want := range g.Records {
		g0 := got[i]
		if g0.Key != want.Key {
			t.Errorf("record %d key: want %q, got %q", i, want.Key, g0.Key)
		}
		for _, h := range stable {
			if g0.Headers[h] != want.Headers[h] {
				t.Errorf("record %d header %s: want %q, got %q", i, h, want.Headers[h], g0.Headers[h])
			}
		}
		if g0.Headers["batch_id"] == "" || g0.Headers["received_at"] == "" {
			t.Errorf("record %d missing batch_id/received_at header", i)
		}
		// Compare the decompressed JSON value structurally.
		gzRaw, err := gunzip(g0.Value, 1<<30)
		if err != nil {
			t.Fatalf("record %d gunzip: %v", i, err)
		}
		var gotVal map[string]any
		if err := json.Unmarshal(gzRaw, &gotVal); err != nil {
			t.Fatalf("record %d value json: %v", i, err)
		}
		if !reflect.DeepEqual(gotVal, want.Value) {
			t.Errorf("record %d value mismatch:\n got: %v\nwant: %v", i, gotVal, want.Value)
		}
	}
}

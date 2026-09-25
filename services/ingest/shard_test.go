package main

import (
	"encoding/json"
	"testing"
	"time"
)

// mkSpan builds a minimal OTLP/JSON span with an optional voice.call_id attribute.
func mkSpan(traceID, spanID, parentID, callID string) map[string]any {
	span := map[string]any{"traceId": traceID, "spanId": spanID}
	if parentID != "" {
		span["parentSpanId"] = parentID
	}
	if callID != "" {
		span["attributes"] = []any{
			map[string]any{"key": "voice.call_id", "value": map[string]any{"stringValue": callID}},
		}
	}
	return span
}

func mkPayload(spans ...map[string]any) map[string]any {
	anySpans := make([]any, len(spans))
	for i, s := range spans {
		anySpans[i] = s
	}
	return map[string]any{
		"resourceSpans": []any{
			map[string]any{
				"resource":   map[string]any{"attributes": []any{}},
				"scopeSpans": []any{map[string]any{"spans": anySpans}},
			},
		},
	}
}

func TestShardKeySelection(t *testing.T) {
	p := mkPayload(
		mkSpan("t1", "s1", "", "call-A"), // keyed by call id
		mkSpan("t1", "s2", "s1", ""),     // same call id via... no attr -> keyed by traceId t1
		mkSpan("t2", "s3", "", ""),       // keyed by traceId t2
	)
	groups := shard(p)
	if len(groups) != 3 {
		t.Fatalf("want 3 groups, got %d: %+v", len(groups), keys(groups))
	}
	if groups[0].key != "call-A" || groups[1].key != "t1" || groups[2].key != "t2" {
		t.Fatalf("unexpected keys/order: %v", keys(groups))
	}
}

func TestBuildRecordsHeadersAndKey(t *testing.T) {
	p := mkPayload(mkSpan("tracehex", "s1", "", "call-A"))
	recs, err := buildRecords(p, "vastu-hfc", "agent-7", "batch123", time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	if len(recs) != 1 {
		t.Fatalf("want 1 record, got %d", len(recs))
	}
	r := recs[0]
	if r.Key != "call-A" {
		t.Errorf("key: want call-A, got %q", r.Key)
	}
	want := map[string]string{
		"org": "vastu-hfc", "agent_id": "agent-7", "shard_key": "call-A",
		"trace_id": "tracehex", "batch_id": "batch123", "seq": "0",
	}
	for k, v := range want {
		if r.Headers[k] != v {
			t.Errorf("header %s: want %q, got %q", k, v, r.Headers[k])
		}
	}
	if r.Headers["received_at"] == "" {
		t.Error("received_at header missing")
	}
}

func TestKeyFallbackTraceThenBatch(t *testing.T) {
	// span with no call id and no traceId -> shard key "", record key falls back to batchID.
	p := mkPayload(mkSpan("", "s1", "", ""))
	recs, err := buildRecords(p, "default", "", "batchXYZ", time.Unix(0, 0))
	if err != nil {
		t.Fatal(err)
	}
	if recs[0].Key != "batchXYZ" {
		t.Errorf("want key batchXYZ, got %q", recs[0].Key)
	}
	if recs[0].Headers["shard_key"] != "" {
		t.Errorf("shard_key should be empty, got %q", recs[0].Headers["shard_key"])
	}
}

func TestSliceValueRoundTrips(t *testing.T) {
	p := mkPayload(mkSpan("t1", "s1", "", "call-A"))
	recs, _ := buildRecords(p, "o", "", "b", time.Unix(0, 0))
	raw, err := gunzip(recs[0].Value, 1<<30)
	if err != nil {
		t.Fatal(err)
	}
	var slice map[string]any
	if err := json.Unmarshal(raw, &slice); err != nil {
		t.Fatal(err)
	}
	rs := slice["resourceSpans"].([]any)
	if len(rs) != 1 {
		t.Fatalf("want 1 resourceSpans, got %d", len(rs))
	}
	scopeSpans := rs[0].(map[string]any)["scopeSpans"].([]any)
	spans := scopeSpans[0].(map[string]any)["spans"].([]any)
	if len(spans) != 1 {
		t.Fatalf("want 1 span in slice, got %d", len(spans))
	}
}

func keys(gs []shardGroup) []string {
	out := make([]string, len(gs))
	for i, g := range gs {
		out[i] = g.key
	}
	return out
}

package main

import (
	"bytes"
	"compress/gzip"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

// captureProducer records everything sent, for handler tests.
type captureProducer struct {
	topic string
	recs  []outRecord
}

func (c *captureProducer) Send(_ context.Context, topic string, recs []outRecord) error {
	c.topic = topic
	c.recs = append(c.recs, recs...)
	return nil
}
func (c *captureProducer) Close() {}

func newTestServer(prod producer) *server {
	return &server{
		cfg:  Config{KafkaTopic: "raw-spans", DevOpen: true},
		prod: prod,
		auth: devOpenAuth{},
	}
}

func TestHandleTracesProducesRecords(t *testing.T) {
	cap := &captureProducer{}
	srv := newTestServer(cap)

	payload := mkPayload(mkSpan("t1", "s1", "", "call-A"))
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set(orgHeader, "vastu-hfc")
	w := httptest.NewRecorder()

	srv.handleTraces(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status: want 200, got %d (%s)", w.Code, w.Body.String())
	}
	if len(cap.recs) != 1 {
		t.Fatalf("want 1 produced record, got %d", len(cap.recs))
	}
	if cap.recs[0].Headers["org"] != "vastu-hfc" {
		t.Errorf("org header: got %q", cap.recs[0].Headers["org"])
	}
	if cap.topic != "raw-spans" {
		t.Errorf("topic: got %q", cap.topic)
	}
	var resp map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &resp)
	if _, ok := resp["partialSuccess"]; !ok {
		t.Errorf("response missing partialSuccess: %s", w.Body.String())
	}
}

func TestHandleTracesBadJSONIs400(t *testing.T) {
	srv := newTestServer(&captureProducer{})
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader([]byte("{not json")))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	srv.handleTraces(w, req)

	if w.Code != http.StatusBadRequest {
		t.Fatalf("want 400, got %d (%s)", w.Code, w.Body.String())
	}
}

// rejectAuth always fails auth, to exercise the 401 path.
type rejectAuth struct{}

func (rejectAuth) identify(_ context.Context, _ http.Header) (identity, error) {
	return identity{}, authErr{"invalid ingest token"}
}

func TestHandleTracesAuthFailureIs401(t *testing.T) {
	cap := &captureProducer{}
	srv := &server{cfg: Config{KafkaTopic: "raw-spans"}, prod: cap, auth: rejectAuth{}}
	payload := mkPayload(mkSpan("t1", "s1", "", "call-A"))
	body, _ := json.Marshal(payload)
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	srv.handleTraces(w, req)

	if w.Code != http.StatusUnauthorized {
		t.Fatalf("want 401, got %d (%s)", w.Code, w.Body.String())
	}
	if len(cap.recs) != 0 {
		t.Errorf("rejected request should not produce, got %d records", len(cap.recs))
	}
}

func TestHandleTracesEmptyBodyIsOK(t *testing.T) {
	cap := &captureProducer{}
	srv := newTestServer(cap)
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(nil))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()

	srv.handleTraces(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d", w.Code)
	}
	if len(cap.recs) != 0 {
		t.Errorf("empty body should produce no records, got %d", len(cap.recs))
	}
}

func TestHandleTracesRejectsOversizedBody(t *testing.T) {
	srv := newTestServer(&captureProducer{})
	srv.cfg.MaxIngestBytes = 100 // tiny cap
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(bytes.Repeat([]byte("x"), 500)))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	srv.handleTraces(w, req)
	if w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("want 413, got %d (%s)", w.Code, w.Body.String())
	}
}

func TestHandleTracesRejectsGzipBomb(t *testing.T) {
	srv := newTestServer(&captureProducer{})
	srv.cfg.MaxIngestBytes = 10 << 20
	srv.cfg.MaxDecodedBytes = 1024 // 1 KiB ceiling
	var buf bytes.Buffer
	zw := gzip.NewWriter(&buf)
	_, _ = zw.Write(bytes.Repeat([]byte{0}, 2<<20)) // 2 MiB of zeros -> tiny gzip
	_ = zw.Close()
	req := httptest.NewRequest("POST", "/v1/traces", bytes.NewReader(buf.Bytes()))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Content-Encoding", "gzip")
	w := httptest.NewRecorder()
	srv.handleTraces(w, req)
	if w.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("want 413, got %d (%s)", w.Code, w.Body.String())
	}
}

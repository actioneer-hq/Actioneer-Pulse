// Command ingest is the Pulse ingest service: an OTLP trace receiver that authenticates, shards each
// batch per call, and produces gzipped span slices to the Kafka raw-spans topic. It is a thin,
// DB-light producer (a token lookup is its only DB touch) — the analysis service consumes, assembles,
// and analyses. It speaks the exact raw-spans contract of the Python reference (voiceobs/ingestion.py).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"time"
)

type server struct {
	cfg  Config
	prod producer
	auth authenticator
}

func main() {
	cfg := loadConfig()
	log.Printf("ingest starting (dev_open=%v topic=%s brokers=%v)", cfg.DevOpen, cfg.KafkaTopic, cfg.KafkaBrokers)

	prod, err := newKafkaProducer(cfg.KafkaBrokers)
	if err != nil {
		log.Fatalf("kafka producer init: %v", err)
	}
	defer prod.Close()

	auth := pickAuth(cfg)
	if c, ok := auth.(interface{ Close() }); ok {
		defer c.Close()
	}
	srv := &server{cfg: cfg, prod: prod, auth: auth}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/traces", srv.handleTraces)
	mux.HandleFunc("GET /health", srv.handleHealth)

	addr := ":" + cfg.Port
	log.Printf("listening on %s", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("server: %v", err)
	}
}

// pickAuth returns the dev-open authenticator under dev-open (token-less ingest allowed), else the
// Postgres-backed token authenticator.
func pickAuth(cfg Config) authenticator {
	if cfg.DevOpen {
		return devOpenAuth{}
	}
	if cfg.DatabaseURL == "" {
		log.Fatal("VOICEOBS_DATABASE_URL required when not dev-open (token auth needs the DB)")
	}
	auth, err := newPGAuth(context.Background(), cfg.DatabaseURL)
	if err != nil {
		log.Fatalf("token auth init: %v", err)
	}
	return auth
}

func (s *server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// handleTraces is the OTLP receiver: authenticate -> decode -> shard -> produce. Always 200 on
// success with {"partialSuccess": {}}, matching the Python endpoint.
func (s *server) handleTraces(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	id, err := s.auth.identify(ctx, r.Header)
	if err != nil {
		var ae authErr
		if errors.As(err, &ae) {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"detail": ae.msg})
			return
		}
		log.Printf("auth error: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "auth failed"})
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, s.cfg.MaxIngestBytes)
	body, err := io.ReadAll(r.Body)
	if err != nil {
		var mbe *http.MaxBytesError
		if errors.As(err, &mbe) {
			writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"detail": "ingest body too large"})
			return
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": "unreadable body"})
		return
	}
	payload, err := decodePayload(body, r.Header.Get("Content-Type"), r.Header.Get("Content-Encoding"), s.cfg.MaxDecodedBytes)
	if err != nil {
		var big errTooLarge
		if errors.As(err, &big) {
			writeJSON(w, http.StatusRequestEntityTooLarge, map[string]string{"detail": big.Error()})
			return
		}
		var bad errBadBody
		if errors.As(err, &bad) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"detail": bad.Error()})
			return
		}
		writeJSON(w, http.StatusBadRequest, map[string]string{"detail": err.Error()})
		return
	}

	recs, err := buildRecords(payload, id.org, id.agentID, newBatchID(), time.Now())
	if err != nil {
		log.Printf("build records: %v", err)
		writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "shard failed"})
		return
	}
	if len(recs) > 0 {
		if err := s.prod.Send(ctx, s.cfg.KafkaTopic, recs); err != nil {
			log.Printf("produce: %v", err)
			writeJSON(w, http.StatusInternalServerError, map[string]string{"detail": "produce failed"})
			return
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"partialSuccess": map[string]any{}})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

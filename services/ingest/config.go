package main

import (
	"os"
	"strconv"
	"strings"
)

// Config is the ingest service's runtime configuration, read once from the environment at startup.
// Keys mirror the Python side's VOICEOBS_* names so a single .env drives both.
type Config struct {
	KafkaBrokers    []string // VOICEOBS_KAFKA_BROKERS, comma-separated
	KafkaTopic      string   // VOICEOBS_KAFKA_TOPIC_RAW, default "raw-spans"
	DatabaseURL     string   // VOICEOBS_DATABASE_URL (Postgres; used for token auth)
	DevOpen         bool     // VOICEOBS_DEV_OPEN, or a sqlite DATABASE_URL — token-less ingest allowed
	Port            string   // VOICEOBS_PORT, default "8000"
	MaxIngestBytes  int64    // VOICEOBS_MAX_INGEST_BYTES — reject a larger request body (default 32 MiB)
	MaxDecodedBytes int64    // VOICEOBS_MAX_DECODED_BYTES — cap gunzip output (default 256 MiB)
}

func loadConfig() Config {
	c := Config{
		KafkaTopic:      envOr("VOICEOBS_KAFKA_TOPIC_RAW", "raw-spans"),
		DatabaseURL:     os.Getenv("VOICEOBS_DATABASE_URL"),
		Port:            envOr("VOICEOBS_PORT", "8000"),
		MaxIngestBytes:  envInt("VOICEOBS_MAX_INGEST_BYTES", 32*1024*1024),
		MaxDecodedBytes: envInt("VOICEOBS_MAX_DECODED_BYTES", 256*1024*1024),
	}
	if b := os.Getenv("VOICEOBS_KAFKA_BROKERS"); b != "" {
		for _, part := range strings.Split(b, ",") {
			if p := strings.TrimSpace(part); p != "" {
				c.KafkaBrokers = append(c.KafkaBrokers, p)
			}
		}
	}
	// dev-open mirrors Config.is_dev_open: the flag, OR a sqlite DB URL (a local source checkout).
	c.DevOpen = truthy(os.Getenv("VOICEOBS_DEV_OPEN")) || strings.HasPrefix(c.DatabaseURL, "sqlite")
	return c
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int64) int64 {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64); err == nil && n > 0 {
			return n
		}
	}
	return def
}

func truthy(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

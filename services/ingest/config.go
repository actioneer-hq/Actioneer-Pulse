package main

import (
	"os"
	"strings"
)

// Config is the ingest service's runtime configuration, read once from the environment at startup.
// Keys mirror the Python side's VOICEOBS_* names so a single .env drives both.
type Config struct {
	KafkaBrokers []string // VOICEOBS_KAFKA_BROKERS, comma-separated
	KafkaTopic   string   // VOICEOBS_KAFKA_TOPIC_RAW, default "raw-spans"
	DatabaseURL  string   // VOICEOBS_DATABASE_URL (Postgres; used for token auth)
	DevOpen      bool     // VOICEOBS_DEV_OPEN, or a sqlite DATABASE_URL — token-less ingest allowed
	Port         string   // VOICEOBS_PORT, default "8000"
}

func loadConfig() Config {
	c := Config{
		KafkaTopic:  envOr("VOICEOBS_KAFKA_TOPIC_RAW", "raw-spans"),
		DatabaseURL: os.Getenv("VOICEOBS_DATABASE_URL"),
		Port:        envOr("VOICEOBS_PORT", "8000"),
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

func truthy(v string) bool {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

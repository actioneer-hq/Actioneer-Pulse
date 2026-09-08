# Pulse ingest (Go)

The production ingest service: an OTLP/HTTP trace receiver that authenticates a producer, shards each
batch per call, and produces gzipped span slices to the Kafka `raw-spans` topic. The Python analysis
service consumes, assembles (Postgres `RawFragment` is the assembly buffer), and analyses.

It is deliberately thin — the only DB touch is ingest-token verification — and speaks the **exact**
`raw-spans` contract of the Python reference (`src/voiceobs/ingestion.py`): same shard key
(`voice.call_id` → `traceId` → `""`), same gzipped-JSON slice value, same headers
(`org, agent_id, shard_key, trace_id, batch_id, seq, received_at`), same key fallback.

## Endpoints
- `POST /v1/traces` — OTLP receiver (JSON + protobuf, gzip-aware). Always `200 {"partialSuccess":{}}`.
- `GET /health`

## Config (env, `VOICEOBS_` prefix)
| var | default | notes |
|---|---|---|
| `VOICEOBS_KAFKA_BROKERS` | — | comma-separated seed brokers |
| `VOICEOBS_KAFKA_TOPIC_RAW` | `raw-spans` | |
| `VOICEOBS_DATABASE_URL` | — | **pgx DSN** (`postgres://…`), for token auth |
| `VOICEOBS_DEV_OPEN` | `false` | truthy → token-less ingest allowed (no DB) |
| `VOICEOBS_PORT` | `8000` | |

## Auth
`Authorization: Bearer vo_<prefix>_<secret>` or `X-Voiceobs-Token`. The org (schema) comes from
`X-Voiceobs-Org` (default `default`); the token is argon2id-verified against `ingest_token` within that
org's `t_<slug>` schema. Verified tokens are cached (TTL LRU) so argon2 doesn't run per request.

## Develop / test
```sh
go test ./...        # unit + cross-language golden + argon2 parity
go vet ./... && gofmt -l .
```
The golden reference (`testdata/records.json`) is produced by the Python `produce()` so the Go output
is checked against the reference implementation itself. Regenerate after any contract change:
```sh
uv run python services/ingest/testdata/gen_golden.py
```

## Integration (compose, end-to-end)
Requires the Docker daemon. Brings up Postgres + Redpanda + Go ingest + Python analysis and flows a
real batch producer→topic→consumer→Postgres:
```sh
docker compose up --build -d db redpanda redpanda-init api ingest analysis
# POST an OTLP batch at the Go ingest (dev-open in compose, so no token needed):
curl -s -X POST localhost:8001/v1/traces -H 'Content-Type: application/json' \
     --data @services/ingest/testdata/sample_call.json
# then confirm the call was assembled + analysed by the Python consumer via the dashboard API:
curl -s localhost:8000/v1/... # (a read endpoint) or inspect Postgres
```

## Contract parity (why this is safe)
`testdata/gen_golden.py` runs the same OTLP fixture the Python suite uses through the real
`voiceobs.ingestion.produce()` and dumps each record; `golden_test.go` feeds the identical fixture
through the Go pipeline and asserts equal key/headers/value. The Python impl remains the spec.

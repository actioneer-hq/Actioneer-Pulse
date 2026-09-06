# Pulse (Pulse)

Consumes OTLP spans from a voice agent and turns one call into one screen.

## Run it

```bash
docker compose up --build
```

Postgres plus the API on `http://localhost:8000`. Migrations run at container start.
Set `VO_PORT` to move it; Postgres is not published at all, so it cannot collide with a
Postgres you already run (`docker compose exec db psql -U voiceobs -d voiceobs`).

Not OTLP's conventional **4318**, on purpose: an otel-collector usually already owns
4317/4318, and you want both reachable while migrating off it. In a deployment where
nothing else claims it, `VO_PORT=4318` is the friendlier choice — a producer already
pointed at a collector then needs only a host change.

```bash
curl localhost:8000/health          # {"status":"ok"}
curl localhost:8000/v1/calls        # {"items": [...]}
```

The UI is at `/`, the API under `/v1`, same origin.

## UI

React + Vite in `ui/`, built into `src/voiceobs/api/static/` and served by the API —
one container, one origin, no CORS.

```bash
npm --prefix ui install
npm --prefix ui run dev     # :5173, proxies /v1 to :8000
npm --prefix ui run build   # into src/voiceobs/api/static/
```

`docker compose build` runs that build in a node stage, so the runtime image carries
no node. The mount is conditional: without a build the API still starts and every
route except `/` works.

## Point a producer at it

Pulse speaks **OTLP/HTTP** — both protobuf (what every SDK exporter sends) and JSON. It
does not speak gRPC, so set the protocol explicitly: an SDK that infers gRPC from a
`:4317`-shaped endpoint fails open, giving silence rather than an error.

```bash
VOICE_OTEL_TRACING=1
VOICE_OTEL_EXPORTER_ENDPOINT=http://<vo-host>:8000
VOICE_OTEL_EXPORTER_PROTOCOL=http/protobuf
```

The SDK appends `/v1/traces` itself. Pulse exposes no `/v1/metrics`, so keep a producer's
metrics exporter pointed somewhere else.

## Configuration

Two layers. **Secrets** go in the environment (`.env`, `VOICEOBS_`-prefixed) — see `.env.example`.
**Everything else**, including which LLM each role uses, lives in **`src/voiceobs/config.py`**
(the central config file — edit `LLM_ROLES` to pick provider/model per role). Non-secret values have
in-file defaults but can still be overridden by env for Docker/12-factor.

Secrets (env only):

| variable | required | meaning |
|---|---|---|
| `VOICEOBS_DATABASE_URL` | yes | SQLAlchemy URL, e.g. `postgresql+psycopg://…` |
| `VOICEOBS_SECRET_KEY` | yes (prod) | signs JWTs + encrypts stored creds |
| `VOICEOBS_BOOTSTRAP_PASSWORD` | first run | initial owner password |
| `VOICEOBS_POST_CALL_API_KEY` | per role | key for the post-call judge model (role active when set) |
| `VOICEOBS_GLOBAL_CHAT_API_KEY` | per role | key for the global-chat model |
| `VOICEOBS_PER_CALL_CHAT_API_KEY` | per role | key for the per-call chat model |

Common non-secret overrides (defaults in `config.py`): `VOICEOBS_SKIP_MIGRATE` (docker entrypoint),
`VOICEOBS_ALLOW_DELETE`, `VOICEOBS_WORKER_POLL_S`/`_BATCH`/`_GRACE_S`.

Running outside Docker:

```bash
pip install -e ".[pg,dev]"
export VOICEOBS_DATABASE_URL=postgresql+psycopg://voiceobs:voiceobs@localhost:5432/voiceobs
alembic upgrade head
uvicorn voiceobs.api.app:app --port 8000
```

The entrypoint migrates on every start. That is right for one container and wrong for
several starting at once — run `alembic upgrade head` as a deploy step and set
`VOICEOBS_SKIP_MIGRATE=1` when you scale past one replica.

## Tests

```bash
pytest -q && ruff check . && lint-imports
```

## Supporting another producer

Pulse reads any OTLP producer. Pipecat, LiveKit or your own is two dicts:

```python
class PipecatAdapter(OTLPAdapter):
    name = "pipecat"
    service_name = "pipecat"
    stages = {"conversation": Stage.CALL, "stt_service": Stage.STT}
    attr_aliases = {"pipecat.turn": "turn.id"}
```

Register it in `adapters/__init__.py` and nothing else changes — `core/` and `worker/`
name no producer, and a test enforces that. A producer with no adapter at all still
gets a call and a timeline via the generic adapter, with its spans marked `unknown`
rather than guessed at.

`attr_aliases` maps onto Pulse's canonical vocabulary; the full list is in
`adapters/generic.py`.

## What does not exist yet

**Audio.** Calls are analysed from spans alone after a quiet period
(`VOICEOBS_WORKER_GRACE_S`), so `caller_utt_end_s` and anything derived from the
waveform stays NULL. No viewer either.

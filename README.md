<div align="center">

# Pulse

**Open-source, self-hosted observability & evals for voice AI agents.**

*OTLP in — one call, one screen. Then compare any two versions of your agent across the checks that matter, before you ship.*

</div>

> [!WARNING]
> We are still actively refining our core concepts, protocols, and specifications. We will likely introduce major breaking changes prior to a stable release.

---

## What is Pulse?

Standard APM shows request latency but is blind to *conversation quality*: did the agent skip the
identity check, hallucinate an amount, talk over the caller, loop on silence, misclassify intent?
Pulse is built for the STT → LLM → TTS pipeline behind a voice agent.

- **Voice-native observability.** Ingest a producer's telemetry, join it on one clock, and render
  one call as one screen — Waterfall timeline, per-turn latency (TTFT, v2v, endpointing),
  interruptions, token/cost rollups, and a **Trust report** that names exactly what evidence was
  missing rather than guessing.
- **Eval-based version comparison.** Turn your real calls into repeatable checks, then see how any
  two versions of your agent performed side by side. Pulse renders the scorecard; your team decides
  whether to ship. No automatic verdict.
- **Self-hosted.** Your calls, transcripts, and audio never leave your infrastructure.

Pulse is the center of truth around **spans**. Turns, metrics, p50/p95, and rollups are *computed by
Pulse*, never trusted from the producer — see [`CONTRACTS.md`](CONTRACTS.md) for the canonical model.

## Quickstart

```bash
git clone https://github.com/Glitchcraft-Inc/Actioneer-Pulse.git
cd Actioneer-Pulse
cp .env.example .env        # set VOICEOBS_SECRET_KEY + VOICEOBS_BOOTSTRAP_PASSWORD
docker compose up --build
```

That brings up Postgres plus the API + UI on `http://localhost:8000` (migrations run at container
start). Postgres itself is not published, so it can't collide with one you already run.

```bash
curl localhost:8000/health          # {"status":"ok"}
curl localhost:8000/v1/calls        # {"items": [...]}
```

The UI is at `/`, the API under `/v1`, same origin — one container, no CORS. Set `VO_PORT` to move
it off `8000`.

## Getting your data in

Pulse has two ingestion paths. Pick by how your agent already stores telemetry.

### 1. Live OTLP (recommended for supported frameworks)

Pulse speaks **OTLP/HTTP** — both protobuf (what every SDK exporter sends) and JSON. It does **not**
speak gRPC, so set the protocol explicitly (an SDK that infers gRPC from a `:4317`-shaped endpoint
fails silently):

```bash
VOICE_OTEL_TRACING=1
VOICE_OTEL_EXPORTER_ENDPOINT=http://<pulse-host>:8000
VOICE_OTEL_EXPORTER_PROTOCOL=http/protobuf
```

The SDK appends `/v1/traces` itself. **LiveKit** and **Pipecat** work out of the box.

### 2. Batch / stored artifacts — via the [Pulse Wizard](https://github.com/Glitchcraft-Inc/Pulse-Wizard)

If your telemetry already lives in blob storage, a database, or log files — in *your own* format —
point the **[Pulse Wizard](https://github.com/Glitchcraft-Inc/Pulse-Wizard)** at your repo. It's an
agent-driven CLI that reads how you actually write telemetry and generates a declarative **integration
manifest**: storage selectors, decoders, and mappers that turn your artifacts into Pulse's canonical
model. Pulse then executes that manifest against your storage — no code changes to your agent.

```bash
# in your voice-agent repo
npx @actioneer/pulse-wizard@latest init
```

The manifest is registered with Pulse (`PUT /v1/ingest/integration-manifest`) and run as a backfill
job. See the [Pulse Wizard README](https://github.com/Glitchcraft-Inc/Pulse-Wizard) for the full flow.

## Integrating your own voice framework (native OTLP)

If your framework emits OTLP but isn't LiveKit or Pipecat, adding a dialect is "copy a folder."
Subclass the generic `OTLPAdapter` with your span/attr names and register it:

```python
# src/voiceobs/frameworks/mystack/__init__.py
from voiceobs.core.model import Stage
from voiceobs.frameworks.generic import OTLPAdapter

class MyStackAdapter(OTLPAdapter):
    name = "mystack"
    version = 1
    # map your span names onto Pulse stages
    stages = {"conversation": Stage.CALL, "stt_service": Stage.STT}
    # map your attributes onto Pulse's canonical vocabulary
    attr_aliases = {"mystack.turn": "turn.id"}
```

Then register it in `src/voiceobs/frameworks/__init__.py`:

```python
from voiceobs.frameworks.mystack import MyStackAdapter
register(Framework("mystack", MyStackAdapter()))
```

Nothing else changes — `core/` and `worker/` name no producer, and a test enforces that. Supply a
`Calculator` subclass only if your producer's timing model differs from the canonical one. The full
canonical attribute vocabulary lives in `src/voiceobs/frameworks/generic.py`.

> A producer that matches no adapter is reported *unsupported* rather than silently reshaped. For
> arbitrary formats that aren't OTLP at all, use the [Pulse Wizard](#2-batch--stored-artifacts--via-the-pulse-wizard) instead.

## Configuration

Two layers:

- **Secrets** → environment (`VOICEOBS_`-prefixed, e.g. in `.env`). See [`.env.example`](.env.example).
- **Everything else**, including which LLM each role uses, lives in
  [`src/voiceobs/config.py`](src/voiceobs/config.py) — edit `LLM_ROLES` to pick provider/model per
  role. Non-secret values have in-file defaults and can still be overridden by env (12-factor).

| variable | required | meaning |
|---|---|---|
| `VOICEOBS_DATABASE_URL` | yes | SQLAlchemy URL, e.g. `postgresql+psycopg://…` |
| `VOICEOBS_SECRET_KEY` | yes (prod) | signs JWTs + encrypts stored creds |
| `VOICEOBS_BOOTSTRAP_PASSWORD` | first run | initial owner password |
| `VOICEOBS_POST_CALL_API_KEY` | per role | key for the post-call judge model |
| `VOICEOBS_GLOBAL_CHAT_API_KEY` | per role | key for the global-chat model |
| `VOICEOBS_PER_CALL_CHAT_API_KEY` | per role | key for the per-call chat model |

Common non-secret overrides: `VOICEOBS_SKIP_MIGRATE`, `VOICEOBS_ALLOW_DELETE`,
`VOICEOBS_WORKER_POLL_S` / `_BATCH` / `_GRACE_S`.

The Docker entrypoint migrates on every start — right for one container, wrong for several starting at
once. When you scale past one replica, run `alembic upgrade head` as a deploy step and set
`VOICEOBS_SKIP_MIGRATE=1`.

## Development

Run the API + workers outside Docker:

```bash
pip install -e ".[pg,dev]"
export VOICEOBS_DATABASE_URL=postgresql+psycopg://voiceobs:voiceobs@localhost:5432/voiceobs
alembic upgrade head
uvicorn voiceobs.api.app:app --port 8000
```

The UI is React + Vite in `ui/`, built into `src/voiceobs/api/static/` and served by the API:

```bash
npm --prefix ui install
npm --prefix ui run dev     # :5173, proxies /v1 to :8000
npm --prefix ui run build   # into src/voiceobs/api/static/
```

`docker compose build` runs that build in a node stage, so the runtime image carries no node.

### Architecture

- **`core/` is pure** — no I/O, no DB, no network (enforced by import-linter). It's essentially two
  pure functions: audio analysis and join.
- **`frameworks/`** — per-producer OTLP dialects; import `core`, never the reverse.
- **`worker/`** — Kafka-decoupled analysis workers.
- **`api/`** — FastAPI + SQLAlchemy + Alembic, schema-per-tenant.

See [`AGENTS.md`](AGENTS.md) for code conventions, [`CONTRACTS.md`](CONTRACTS.md) for the canonical
model, and [`docs/PULSE-SPEC.md`](docs/PULSE-SPEC.md) for the product spec.

### Tests & lint

```bash
pytest -q && ruff check . && lint-imports
```

## Telemetry

Pulse can send **anonymous usage telemetry** — aggregate product signals only (version, which producer
adapter runs, which features are on, bucketed counts, anonymized error codes). It **never** sends
tenant data: no org names, endpoints, tokens, call content, transcripts, metric values, or file paths.

It is **inert until you set `VOICEOBS_TELEMETRY_ENDPOINT`**, and is disabled by
`VOICEOBS_TELEMETRY_DISABLED=1`, the standard `DO_NOT_TRACK=1`, or `CI=true`.

## Contributing

Contributions are welcome. To get started:

1. **Fork & branch.** Branch off `main`; keep changes focused.
2. **Follow the conventions** in [`AGENTS.md`](AGENTS.md) — concise code, Pydantic v2 for in-memory
   types, SQLAlchemy 2.0 for the DB layer, and the `core/` purity rule.
3. **Before you push**, make sure the checks are green:
   ```bash
   pytest -q && ruff check . && lint-imports
   ```
4. **Open a PR** against `main` with a clear description of the change and why. Adapters for new
   frameworks and Wizard mappers for new storage layouts are especially welcome.

Found a bug or have an idea? Open an
[issue](https://github.com/Glitchcraft-Inc/Actioneer-Pulse/issues).

## Related projects

- **[Pulse Wizard](https://github.com/Glitchcraft-Inc/Pulse-Wizard)** — agent-driven CLI that maps
  your existing telemetry storage into Pulse's canonical model.

## License

License TBD — see repository settings.

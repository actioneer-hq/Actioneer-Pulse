# AGENTS.md

Conventions for coding agents on this repo (Pulse — voice observability). Living doc; extend as we go.

## Code style

- **Concise over verbose.** No essay docstrings, no comments that restate the code. Comment *why*, never *what*. A one-line module docstring is usually enough; put rationale in the design docs, not in every file.
- **Readable to humans, not just AI.** Prefer short functions, small helpers, and tables over repeated blocks. If a pattern repeats ~3+ times, extract a helper.
- Match the surrounding code's density and idiom.

## Types & models

- **Use Pydantic v2 `BaseModel`, not stdlib `@dataclass`**, for all in-memory types. Frozen by default:
  ```python
  class Frozen(BaseModel):
      model_config = ConfigDict(frozen=True)
  ```
  BaseModel is keyword-only — construct with named args.
- **DB layer is SQLAlchemy 2.0** (`db/`). Pydantic is not an ORM; don't mix them.

## Architecture rules

- **`core/` is pure** — no I/O, no DB, no network. Enforced by import-linter (`voiceobs.core` must not import `api/adapters/storage/worker/db`). Keep it that way.
- The whole of `core` is two pure functions: `analyze_audio` (Layer 1) and `join` (Layer 2).
- `channel_map` decides caller vs agent — **never assume ch0 = caller**.

## Before committing

- `ruff check .` — clean
- `pytest -q` — green
- `lint-imports` — core purity KEPT
- Design docs (`PLAN.md`, `CONTRACTS.md`, `MODELS.md`, `CONTEXT.md`) and `*.pdf` are gitignored — kept local, not committed.

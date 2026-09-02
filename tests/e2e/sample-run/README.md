# Sample end-to-end run — LiveKit agent, real voice

A ~2-minute live conversation with the `tests/e2e/agent.py` LiveKit agent (cascade
STT→LLM→TTS, OpenAI), captured to show the full path: **voice → OTLP → adapter → join
→ metrics**.

## Files
- **`otlp.json`** — the original OTLP the LiveKit agent exported, reconstructed verbatim
  from the stored raw fragments (134 spans, `service.name: livekit`). This is the raw
  input, before any VO processing.
- **`analysis.json`** — VO's own output for the call (`GET /v1/calls/{id}`): header,
  the 7 turns with their per-stage waterfall, the metrics list, trust block, and the
  span tree. Our analysis, in JSON (not markdown).

## No `.wav` here
LiveKit streams us spans, not audio, so this call is **Layer-2 only** (spans/waterfall).
Layer-1 audio metrics (waveform, talk-ratio, barge-in) need the call audio, which would
be added via LiveKit track egress → `audio_caller`/`audio_agent` artifacts (see
`../README.md`). That wasn't wired for this run, so there are no WAVs.

## What to look for in `analysis.json`
- 7 turns; `unattributed_spans: 4` (turn grouping working — child spans attached).
- Per turn: `stt_final_at`, `tts_start_at`, `response_latency_ms`, `tokens_in`/`out`,
  and `llm_ttft_reported_ms` / `tts_ttfb_reported_ms` (LiveKit reports latency as span
  attributes, so it lands in the *reported* fields; the event-derived `llm_ttft_ms`/
  `tts_ttfb_ms` are null — LiveKit emits no first-token/first-audio events).
- Call-level metrics: `llm_ttft_reported_ms ≈ 897ms`, `tts_ttfb_reported_ms ≈ 1504ms`,
  `tokens_per_turn ≈ 30.6`, `response_latency_ms ≈ 907ms`.

## Bugs this run caught (now fixed + regression-tested)
1. `turn_index` collision for producers without `turn.index` (positional fallback).
2. Turn grouping by span **hierarchy**, not a `turn_id` attribute (generic adapter).
3. LiveKit's real tree (`user_turn` + sibling `agent_turn`, `lk.response.ttft/ttfb`,
   tokens on the `llm_request` sub-span) — the LiveKit adapter + multi-span stage reads.

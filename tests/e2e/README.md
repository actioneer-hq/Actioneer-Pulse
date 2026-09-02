# E2E: talk to a LiveKit agent, watch VO pull the metrics

A minimal cascade agent (`agent.py`) that you talk to in the browser while it streams
OpenTelemetry traces to VO. This validates the **spans → adapter → join → metrics** path
end to end with your real voice.

> Scope: this exercises **Layer 2** (spans/waterfall). LiveKit does not send us the call
> audio, so Layer-1 audio metrics (waveform, talk-ratio, barge-in) stay empty this round.
> LiveKit reports TTFT/TTFB as span attributes → they land in the `*_reported_ms` fields.

## 0. Bring VO up (one terminal each)

```bash
# from the repo root, with the VO venv + a Postgres running
export VOICEOBS_DATABASE_URL=postgresql+psycopg://...   # your DB
alembic upgrade head
uvicorn voiceobs.api.app:app --port 8000                # API  (terminal 1)
python -m voiceobs.worker                                # worker (terminal 2)
```

## 1. LiveKit CLI + auth (from the deploy dialog)

```bash
brew install livekit-cli
lk cloud auth            # opens the browser, links this machine to your project
```

## 2. The agent (a separate venv — keep it off the VO package)

```bash
cd tests/e2e
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill LIVEKIT_*, OPENAI_API_KEY; VO_OTLP_ENDPOINT is preset
python agent.py download-files   # one-time: pull the silero VAD model
python agent.py dev              # runs the agent, connected to your LiveKit project
```

## 3. Talk to it

Open the **Agents Playground**: <https://agents-playground.livekit.io> → pick your
project → **Connect** → allow the mic. Speak; the agent replies. Hang up when done.

(Alternatively `lk app create --template agent-starter-python <app>` scaffolds a full
web client, but the playground is the fastest way to just talk.)

## 4. See the metrics in VO

```bash
curl localhost:8000/v1/calls                      # the call appears (source "livekit")
curl localhost:8000/v1/calls/<id> | jq .          # header, turns, waterfall, metrics
```

Expect: turns with per-stage timing, tokens, and `llm_ttft_reported_ms` /
`tts_ttfb_reported_ms` populated; `disposition` = connected once judged (if a JudgeConfig
is set for the tenant).

## Audio (track egress) — optional, lights up Layer 1

VO accepts the call audio as **one stereo `audio` artifact OR two mono ones**
(`audio_caller` + `audio_agent`) — it combines the two into a caller/agent stereo
stream and runs the audio metrics. Per your design: the **caller** channel drives the
user-side metrics; the **agent** channel is a cross-check against the agent's OTLP.

To produce the two files with **LiveKit Track Egress**:
1. In the LiveKit dashboard/API, start **track egress** for the caller's audio track
   and the agent's audio track → your **S3** bucket (two files).
2. Egress writes OGG/Opus; our decoder wants PCM16 WAV — transcode each once
   (`ffmpeg -i in.ogg out.wav`) or point egress at a WAV output if available.
3. Register both against the call (its id = the OTLP `trace_id` VO keyed it on):
   ```bash
   python register_audio.py <trace_id> s3://bucket/caller.wav s3://bucket/agent.wav
   ```
4. The worker (with your S3 creds in its env) fetches, combines, and computes Layer 1
   on the next tick. `GET /v1/calls/<id>` now shows peaks, talk_ratio, barge_in, etc.

Find the `trace_id` from `GET /v1/calls` (it's the call `id` for LiveKit) after you talk.

## Notes
- The agent runs **locally**, so its OTLP exporter can reach `localhost:8000`. If VO runs
  elsewhere, set `VO_OTLP_ENDPOINT` accordingly and make sure it's reachable.
- Our LiveKit adapter matches on the `agent_session` span LiveKit emits when telemetry is
  on — no per-call config needed.

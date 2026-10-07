# Uploading calls (file onboarding)

Create a project, set its **script**, then **Analyse calls**. Every upload is an **audio ZIP plus exactly
one of these two files** — call parameters are always required:

| Mode | Files | Pulse does |
|---|---|---|
| **Audio + parameters** | ZIP + **CSV** of call parameters | Transcribes every call with Sarvam STT (timestamped), then analyses |
| **Audio + transcripts** | ZIP + **JSON** (`pulse.calls.v1`) with transcripts *and* parameters | Skips transcription, analyses directly |

**Checked before anything runs** — any problem rejects the upload with the exact list, so nothing is
half-analysed: the project has a script (or the JSON brings one); every call has a value for every
`{{placeholder}}` in the script; every audio file has a row and every row has an audio file.

## CSV — call parameters

The columns are `call_id` plus one per placeholder in **your** script. For a script containing
`{{customer_name}}` and `{{due_amount}}`:

```csv
call_id,customer_name,due_amount
<audio file name without extension>,<customer_name>,<due_amount>
```

- `call_id` = the audio file name without its extension (`call-0042.wav` → `call-0042`).
- Every row needs a value in every placeholder column. UTF-8, header row, one row per audio file.

## JSON — `pulse.calls.v1`

```json
{
  "format": "pulse.calls.v1",
  "script": "<optional: the agent's prompt with {{placeholders}}>",
  "calls": [
    {
      "call_id": "<audio file name without extension>",
      "audio_file": "<optional: file name inside the ZIP>",
      "started_at": "<optional: ISO-8601>",
      "params": {"customer_name": "<value>", "due_amount": "<value>"},
      "transcript": [
        {"speaker": "agent", "text": "<what the agent said>", "start": 0.4, "end": 4.1},
        {"speaker": "customer", "text": "<what the customer said>", "start": 5.0, "end": 5.9}
      ]
    }
  ]
}
```

| Field | Notes |
|---|---|
| `script` | Optional. Becomes the project's next script version. |
| `call_id` | Letters, digits and `. _ : @ + -`, up to 128 chars, unique. Audio = `audio_file`, else `<call_id>.<ext>`. |
| `params` | Required: one key per script placeholder. The judge treats the values as ground truth. |
| `transcript` | `speaker` is `agent` or `customer`; `start`/`end` in seconds from the recording start. A call without one is transcribed. |

The UI shows the exact CSV columns and the JSON Schema (with `params` pinned to your placeholders) for
each project, with a Copy button. Same data: `GET /v1/uploads/format?agent_id=<project>`.

## Transcription and latency

Stereo WAV (agent and customer on separate channels) is split by channel, so speakers and timings are
exact; mono or compressed audio goes through Sarvam's diarization. Pick the agent's channel or leave it on
auto-detect. Response latency is the gap between the customer stopping and the agent starting, measured
from the recording — broad numbers, not pipeline-internal timings.

## Running it

- `VOICEOBS_SARVAM_API_KEY` — needed for the CSV mode (transcription).
- Uploaded audio is stored under `VOICEOBS_UPLOAD_DIR` (compose: the shared `voiceobs-uploads` volume).
- Limits: `VOICEOBS_MAX_UPLOAD_BYTES` (default 4 GiB), `VOICEOBS_MAX_UPLOAD_FILES` (default 5000).

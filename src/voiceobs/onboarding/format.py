"""What Pulse accepts for a file upload — exactly one of:

1. **CSV of call parameters** (`call_id` + one column per script placeholder) + an audio ZIP -> Pulse
   transcribes.
2. **JSON `pulse.calls.v1`** (per call: params + transcript; optional top-level script) -> no STT. The
   audio ZIP is optional (playback only); without it every call needs its transcript.

Call parameters are always required: every `{{placeholder}}` in the script needs a value per call.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

FORMAT_ID = "pulse.calls.v1"
_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}$"
Param = str | int | float | bool | None


class Utterance(BaseModel):
    """One stretch of speech. Times are seconds from the start of the call recording."""

    speaker: Literal["agent", "customer"]
    text: str = Field(min_length=1, max_length=20_000)
    start: float = Field(ge=0)
    end: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self) -> Utterance:
        if self.end is not None and self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class UploadCall(BaseModel):
    call_id: str = Field(pattern=_ID_PATTERN)
    audio_file: str | None = Field(default=None, max_length=512)  # name inside the ZIP
    started_at: datetime | None = None
    params: dict[str, Param] = Field(default_factory=dict)  # the prompt's per-call parameters
    transcript: list[Utterance] | None = None

    @field_validator("transcript")
    @classmethod
    def _non_empty(cls, v):
        if v is not None and not v:
            raise ValueError("transcript, when given, must have at least one utterance")
        return sorted(v, key=lambda u: u.start) if v else v


class UploadManifest(BaseModel):
    format: Literal["pulse.calls.v1"]
    script: str | None = Field(default=None, max_length=200_000)  # the agent's prompt / script
    calls: list[UploadCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> UploadManifest:
        seen: set[str] = set()
        dup = {c.call_id for c in self.calls if c.call_id in seen or seen.add(c.call_id)}
        if dup:
            raise ValueError(f"duplicate call_id: {', '.join(sorted(dup)[:5])}")
        return self


class ManifestError(ValueError):
    """The uploaded JSON is not a valid pulse.calls.v1 file; `errors` are human-readable."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def parse_manifest(raw: bytes) -> UploadManifest:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ManifestError([f"not valid JSON: {e}"]) from e
    try:
        return UploadManifest.model_validate(data)
    except ValidationError as e:
        raise ManifestError([
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in e.errors()[:20]
        ]) from e


PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")


def placeholders(script: str | None) -> list[str]:
    """The script's `{{name}}` placeholders, in first-seen order."""
    seen: dict[str, None] = {}
    for m in PLACEHOLDER.finditer(script or ""):
        seen.setdefault(m.group(1), None)
    return list(seen)


def parse_params_csv(raw: bytes) -> dict[str, dict[str, str]]:
    """CSV (`call_id` + parameter columns) -> {call_id: {param: value}}. Raises ManifestError."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ManifestError(["the CSV must be UTF-8 text"]) from e
    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip() for c in (reader.fieldnames or [])]
    if "call_id" not in cols:
        raise ManifestError(["the CSV needs a 'call_id' column (the audio file name without extension)"])
    errors: list[str] = []
    rows: dict[str, dict[str, str]] = {}
    for n, row in enumerate(reader, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        cid = row.pop("call_id", "")
        if not re.match(_ID_PATTERN, cid):
            errors.append(f"line {n}: invalid call_id '{cid}'")
        elif cid in rows:
            errors.append(f"line {n}: duplicate call_id '{cid}'")
        else:
            rows[cid] = {k: v for k, v in row.items() if k}
        if len(errors) >= 20:
            break
    if errors:
        raise ManifestError(errors)
    if not rows:
        raise ManifestError(["the CSV has no rows"])
    return rows


def json_schema(params: list[str]) -> dict:
    """The pulse.calls.v1 JSON Schema, with `params` pinned to this project's placeholders
    (each a required key) so the schema alone says exactly what a call must carry."""
    schema = UploadManifest.model_json_schema()
    call = schema["$defs"]["UploadCall"]
    call["properties"]["params"] = {
        "type": "object", "description": "Per-call values for the script's {{placeholders}}",
        "properties": {p: {"type": ["string", "number", "boolean"]} for p in params},
        "required": list(params),
    }
    call["required"] = sorted(set(call.get("required", [])) | {"call_id", "params"})
    return schema


def format_spec(script: str | None) -> dict:
    """GET /v1/uploads/format: the two accepted side files as schemas, derived from the project's
    script — the CSV columns and the JSON `params` are its `{{placeholders}}`. No script, no schema."""
    params = placeholders(script)
    return {
        "format": FORMAT_ID,
        "has_script": bool(script and script.strip()),
        "params": params,
        "csv": {"columns": ["call_id", *params],
                "example": ",".join(["call_id", *params]) + "\n"
                           + ",".join(["<audio file name without extension>", *(f"<{p}>" for p in params)])},
        "json": {"schema": json_schema(params)},
    }

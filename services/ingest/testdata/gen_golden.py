"""Generate the cross-language golden reference from the Python `produce()` — the executable spec the
Go ingest must match. Runs the same OTLP fixture the Python suite uses through the real produce() path
against an in-memory bus, then dumps each raw-spans record (key, headers, and the *decompressed* JSON
value) to records.json. The Go golden test feeds the identical fixture through the Go pipeline and
asserts equality (ignoring per-run batch_id/received_at).

Run from the repo root:  uv run python services/ingest/testdata/gen_golden.py
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from voiceobs.bus.memory import InMemoryBus
from voiceobs.ingestion import produce

# The fixture lives under tests/ — import it directly.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tests.fixtures.livekit_call import sample_call  # noqa: E402

ORG = "vastu-hfc"
AGENT_ID = "agent-7"
TOPIC = "raw-spans"


def main() -> None:
    bus = InMemoryBus()
    payload = sample_call()
    produce(bus, TOPIC, payload, org=ORG, agent_id=AGENT_ID)

    out = {"org": ORG, "agent_id": AGENT_ID, "topic": TOPIC, "payload": payload, "records": []}
    for rec in bus.records(TOPIC):
        value = json.loads(gzip.decompress(rec.value))
        out["records"].append({"key": rec.key, "headers": rec.headers, "value": value})

    dest = Path(__file__).with_name("records.json")
    dest.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"wrote {dest} ({len(out['records'])} records)")


if __name__ == "__main__":
    main()

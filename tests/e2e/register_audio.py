"""Register two mono track-egress files as a call's audio, so VO runs Layer 1.

    python register_audio.py <call_id> <caller_s3_uri> <agent_s3_uri> [--vo http://localhost:8000]

VO combines audio_caller + audio_agent into a caller/agent stereo stream.
"""

from __future__ import annotations

import argparse

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("call_id")
    ap.add_argument("caller_uri")
    ap.add_argument("agent_uri")
    ap.add_argument("--vo", default="http://localhost:8000")
    ap.add_argument("--sample-rate", type=int, default=8000)
    args = ap.parse_args()

    for kind, uri in (("audio_caller", args.caller_uri), ("audio_agent", args.agent_uri)):
        r = httpx.post(
            f"{args.vo}/v1/calls/{args.call_id}/artifacts",
            json={"kind": kind, "uri": uri, "sample_rate": args.sample_rate,
                  "channel_map": {0: "caller", 1: "agent"}},
        )
        r.raise_for_status()
        print(kind, "->", r.json())


if __name__ == "__main__":
    main()

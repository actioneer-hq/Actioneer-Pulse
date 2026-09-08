"""Produce/consume helpers for the judge queue. Judging is decoupled from analysis: the analysis and
backfill workers enqueue a tiny {org, call_id} message (after the DB commit) instead of calling the LLM
inline, and a dedicated judge worker drains it at a bounded rate. Realtime and backfill use separate
topics so a large backfill never starves live judging."""

from __future__ import annotations

import json

from voiceobs.bus import Producer, Record
from voiceobs.config import get_config


def enqueue_judge(producer: Producer, org: str, call_id: str, *, backfill: bool) -> None:
    """Queue a call for judging. `backfill` routes to the lower-priority backfill topic."""
    c = get_config()
    topic = c.kafka_topic_judge_backfill if backfill else c.kafka_topic_judge
    value = json.dumps({"org": org, "call_id": call_id}).encode()
    producer.send(topic, call_id, value, {"org": org})


def decode_judge(record: Record) -> tuple[str, str]:
    """A judge-request record → (org, external_call_id)."""
    body = json.loads(record.value)
    return body.get("org") or record.headers.get("org") or "default", body["call_id"]

"""Training-data export (/v1/export/training) over the base Call/Turn/Judgment/Prompt model."""
from __future__ import annotations

import json

from voiceobs.db.models import Call, Judgment, Prompt, Turn


def _seed(db_sessionmaker) -> None:
    with db_sessionmaker() as db:
        db.add(Prompt(id="p1", template_sha256="sha1", text="SCRIPT: be helpful; call tools."))
        db.add(Call(id="c1", external_call_id="call-1", source="s", environment="prod",
                    agent_id="a1", prompt_id="p1", status="ingested", metric_version=1))
        # opening agent greeting, then a caller turn whose agent reply was wrong
        db.add(Turn(call_id="c1", turn_index=0, turn_id="c1:0", trigger="opening",
                    llm_spoken="Hello, this is the assistant."))
        db.add(Turn(call_id="c1", turn_index=1, turn_id="c1:1", trigger="endpoint",
                    caller_transcript="I'll pay tomorrow.",
                    llm_spoken="Please pay soon or fees apply."))
        db.add(Judgment(
            call_id="c1", status="ok", disposition="connected", model_fault="llm",
            objective_achieved="no",
            llm_corrections=[
                {"turn_id": "x", "kind": "tool_call",
                 "observed": "Please pay soon or fees apply.",
                 "corrected": "silently record the promise",
                 "corrected_tool": "pay_shortly", "corrected_args": {"date": "tomorrow"}},
                {"turn_id": "y", "kind": "response",
                 "observed": "Please pay soon or fees apply.",
                 "corrected": "Great — I've noted tomorrow. Thank you."},
            ],
        ))
        db.commit()


def test_sft_export(authed_client, db_sessionmaker) -> None:
    _seed(db_sessionmaker)
    r = authed_client.get("/v1/export/training", params={"format": "sft"})
    assert r.status_code == 200
    rows = [json.loads(x) for x in r.text.strip().splitlines()]
    assert len(rows) == 2
    row = rows[0]
    roles = [m["role"] for m in row["messages"]]
    # system + the conversation BEFORE the faulty agent turn (greeting + caller line), then target
    assert roles[0] == "system" and "SCRIPT" in row["messages"][0]["content"]
    assert {"role": "user", "content": "I'll pay tomorrow."} in row["messages"]
    target = row["messages"][-1]
    assert target["role"] == "assistant"
    # tool correction → structured tool_calls; keyed off corrected_tool, not kind
    assert target["tool_calls"][0]["function"]["name"] == "pay_shortly"
    assert row["meta"]["gt_source"] == "judge_unverified"
    assert row["meta"]["recoverable"] is True  # objective != yes + llm fault + correction
    # the text correction is the second row → plain-text target
    assert rows[1]["messages"][-1]["content"].startswith("Great")


def test_dpo_export(authed_client, db_sessionmaker) -> None:
    _seed(db_sessionmaker)
    r = authed_client.get("/v1/export/training", params={"format": "dpo"})
    assert r.status_code == 200
    rows = [json.loads(x) for x in r.text.strip().splitlines()]
    assert len(rows) == 2
    row = rows[0]
    assert row["prompt"]["messages"][0]["role"] == "system"
    assert row["chosen"]["tool_calls"][0]["function"]["name"] == "pay_shortly"
    assert row["rejected"] == {"role": "assistant", "content": "Please pay soon or fees apply."}


def test_bad_format_400(authed_client) -> None:
    assert authed_client.get("/v1/export/training", params={"format": "grpo"}).status_code == 400

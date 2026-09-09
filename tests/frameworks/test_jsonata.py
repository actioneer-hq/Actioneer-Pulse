"""JSONataAdapter: a tenant-supplied JSONata expression -> canonical Trace.

Proves the data-driven path reproduces the hard parts of a real dialect (LiveKit): span-name -> stage,
ns -> seconds, sibling agent_turn re-stitched to the preceding user_turn, and the `lk.llm_metrics`
JSON-*string* blob expanded via `$eval`. The expression here is illustrative (what the wizard would
generate); the point is that the adapter runs it and builds a valid Trace."""

from __future__ import annotations

import pytest

from tests.fixtures.livekit_call import sample_call
from voiceobs.core.model import Stage
from voiceobs.frameworks.base import UnsupportedSchema
from voiceobs.frameworks.jsonata import JSONataAdapter

# producer OTLP payload -> {header, spans[]} canonical Trace JSON
EXPR = r"""
(
  $spans := resourceSpans.scopeSpans.spans;
  $res := $merge(resourceSpans[0].resource.attributes.{ key: value.stringValue });
  $val := function($v){ $exists($v.stringValue) ? $v.stringValue : $exists($v.boolValue) ? $v.boolValue
                        : $exists($v.intValue) ? $number($v.intValue)
                        : $exists($v.doubleValue) ? $v.doubleValue : null };
  $flat := function($s){ $merge($s.attributes.{ key: $val(value) }) };
  $root := $spans[$not($exists(parentSpanId))];
  $t0 := $number($root.startTimeUnixNano);
  $sec := function($ns){ $round(($number($ns)-$t0)/1e9, 6) };
  $stage := { "agent_session":"call","user_turn":"turn","agent_turn":"turn","user_speaking":"speech",
              "eou_detection":"stt","llm_request":"llm","tts_request":"tts","agent_speaking":"playout" };
  $users := $spans[name="user_turn"];
  $turnId := function($s){
    $s.name="user_turn" ? $s.spanId :
    $s.name="agent_turn" ? ($users[$number(startTimeUnixNano) <= $number($s.startTimeUnixNano)]
                             ^(startTimeUnixNano))[-1].spanId : null };
  $llmAttrs := function($f){
    $exists($f.`lk.llm_metrics`) ? ($m:=$eval($f.`lk.llm_metrics`);
        { "metrics.ttft": $m.ttft, "gen_ai.usage.output_tokens": $m.completion_tokens,
          "gen_ai.usage.input_tokens": $m.prompt_tokens }) : {} };
  {
    "header": {
      "call_id": $root.traceId, "source": $res.`service.name`,
      "environment": $res.`deployment.environment`,
      "started_at": $fromMillis($t0/1e6),
      "ended_at": $fromMillis($number($root.endTimeUnixNano)/1e6)
    },
    "spans": $spans.($s:=$; $f:=$flat($s); {
      "span_id": $s.spanId,
      "parent_span_id": $exists($s.parentSpanId) ? $s.parentSpanId : null,
      "name": $s.name, "stage": $lookup($stage, $s.name),
      "t_start": $sec($s.startTimeUnixNano), "t_end": $sec($s.endTimeUnixNano),
      "turn_id": $turnId($s), "error": false,
      "attrs": $merge([
        $s.name="user_turn" and $exists($f.`turn.index`) ? {"turn.index": $f.`turn.index`} : {},
        $s.name="eou_detection" and $exists($f.`lk.transcript_confidence`)
            ? {"stt.confidence": $f.`lk.transcript_confidence`} : {},
        $llmAttrs($f) ])
    })
  }
)
"""


def test_jsonata_maps_livekit_to_canonical_trace():
    trace = JSONataAdapter(EXPR, version=3).to_trace(sample_call())
    by = {s.span_id: s for s in trace.spans}

    # header + structural
    assert trace.header.call_id == "c1c1" * 8
    assert trace.header.source == "livekit"
    assert trace.header.environment == "prod"

    # span-name -> stage
    assert by["eou"].stage is Stage.STT
    assert by["lreq"].stage is Stage.LLM
    assert by["ut"].stage is Stage.TURN

    # ns -> seconds
    assert by["ut"].t_start == 0.9

    # attribute rename + sibling agent_turn re-stitched to the preceding user_turn
    assert by["eou"].attrs["stt.confidence"] == 0.67
    assert by["at"].turn_id == "ut"

    # the lk.llm_metrics JSON-string blob expanded via $eval
    assert by["lreq"].attrs["metrics.ttft"] == 0.3
    assert by["lreq"].attrs["gen_ai.usage.output_tokens"] == 42


def test_bad_expression_raises_unsupported_schema():
    with pytest.raises(UnsupportedSchema):
        JSONataAdapter("this is ( not valid jsonata", version=1).to_trace(sample_call())


def test_non_trace_output_raises_unsupported_schema():
    # a syntactically fine expression that returns something that isn't a Trace object
    with pytest.raises(UnsupportedSchema):
        JSONataAdapter('"just a string"', version=1).to_trace(sample_call())

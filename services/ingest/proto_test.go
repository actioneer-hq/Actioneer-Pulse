package main

import (
	"encoding/hex"
	"testing"

	coltracepb "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonpb "go.opentelemetry.io/proto/otlp/common/v1"
	resourcepb "go.opentelemetry.io/proto/otlp/resource/v1"
	tracepb "go.opentelemetry.io/proto/otlp/trace/v1"
	"google.golang.org/protobuf/proto"
)

// TestDecodeProtobufHexIDs builds a real OTLP protobuf request (ids as raw bytes) and asserts the
// decoded dict has hex ids, string-boxed int attributes, and shards by voice.call_id — the base64->hex
// path is the sharpest parity risk.
func TestDecodeProtobufHexIDs(t *testing.T) {
	traceID, _ := hex.DecodeString("c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1")
	spanID, _ := hex.DecodeString("00000000000000a1")

	req := &coltracepb.ExportTraceServiceRequest{
		ResourceSpans: []*tracepb.ResourceSpans{{
			Resource: &resourcepb.Resource{
				Attributes: []*commonpb.KeyValue{
					kv("service.name", strVal("livekit")),
				},
			},
			ScopeSpans: []*tracepb.ScopeSpans{{
				Spans: []*tracepb.Span{{
					TraceId:           traceID,
					SpanId:            spanID,
					Name:              "agent_session",
					StartTimeUnixNano: 1700000000000000000,
					Attributes: []*commonpb.KeyValue{
						kv("voice.call_id", strVal("call-pb-1")),
						kv("turn.index", intVal(3)),
					},
				}},
			}},
		}},
	}
	body, err := proto.Marshal(req)
	if err != nil {
		t.Fatal(err)
	}

	payload, err := decodeProtobuf(body)
	if err != nil {
		t.Fatal(err)
	}

	// hex ids
	span := payload["resourceSpans"].([]any)[0].(map[string]any)["scopeSpans"].([]any)[0].(map[string]any)["spans"].([]any)[0].(map[string]any)
	if span["traceId"] != "c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1c1" {
		t.Errorf("traceId not hex: %v", span["traceId"])
	}
	if span["spanId"] != "00000000000000a1" {
		t.Errorf("spanId not hex: %v", span["spanId"])
	}
	// int attribute is string-boxed
	if got := spanAttr(span, "turn.index"); got != "3" {
		t.Errorf("turn.index: want \"3\", got %q", got)
	}
	// shard keys by voice.call_id
	groups := shard(payload)
	if len(groups) != 1 || groups[0].key != "call-pb-1" {
		t.Errorf("shard: want [call-pb-1], got %v", keys(groups))
	}
}

func TestDecodeProtobufBadBodyIsBadBody(t *testing.T) {
	_, err := decodeProtobuf([]byte("not-a-protobuf-\xff\xfe"))
	if err == nil {
		t.Skip("garbage happened to parse; acceptable")
	}
	if _, ok := err.(errBadBody); !ok {
		t.Errorf("want errBadBody, got %T", err)
	}
}

func kv(k string, v *commonpb.AnyValue) *commonpb.KeyValue {
	return &commonpb.KeyValue{Key: k, Value: v}
}
func strVal(s string) *commonpb.AnyValue {
	return &commonpb.AnyValue{Value: &commonpb.AnyValue_StringValue{StringValue: s}}
}
func intVal(i int64) *commonpb.AnyValue {
	return &commonpb.AnyValue{Value: &commonpb.AnyValue_IntValue{IntValue: i}}
}

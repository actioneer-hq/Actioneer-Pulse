package main

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"

	coltracepb "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
)

// decodeProtobuf decodes an OTLP/protobuf ExportTraceServiceRequest into the OTLP/JSON dict shape the
// rest of the pipeline expects, matching Python's decode_protobuf: protojson renders the message in
// OTLP/JSON form (camelCase, int64/UnixNano as strings, AnyValue boxed) but emits the id byte-fields
// as base64 — so we convert traceId/spanId/parentSpanId (and the same inside links[]) to hex, exactly
// like Python's _hexify. Skipping that silently breaks parent links.
func decodeProtobuf(body []byte) (map[string]any, error) {
	var msg coltracepb.ExportTraceServiceRequest
	if err := proto.Unmarshal(body, &msg); err != nil {
		return nil, errBadBody{err}
	}
	jsonBytes, err := protojson.MarshalOptions{UseProtoNames: false, EmitUnpopulated: false}.Marshal(&msg)
	if err != nil {
		return nil, errBadBody{err}
	}
	var payload map[string]any
	if err := json.Unmarshal(jsonBytes, &payload); err != nil {
		return nil, errBadBody{err}
	}
	hexifyPayload(payload)
	return payload, nil
}

var idKeys = []string{"traceId", "spanId", "parentSpanId"}

func hexifyPayload(payload map[string]any) {
	for _, rsAny := range asSlice(payload["resourceSpans"]) {
		rs, _ := rsAny.(map[string]any)
		for _, scAny := range asSlice(rs["scopeSpans"]) {
			sc, _ := scAny.(map[string]any)
			for _, spanAny := range asSlice(sc["spans"]) {
				span, _ := spanAny.(map[string]any)
				hexifyIDs(span)
				for _, linkAny := range asSlice(span["links"]) {
					if link, ok := linkAny.(map[string]any); ok {
						hexifyIDs(link)
					}
				}
			}
		}
	}
}

// hexifyIDs rewrites base64 id fields to hex in place.
func hexifyIDs(d map[string]any) {
	if d == nil {
		return
	}
	for _, k := range idKeys {
		if s, ok := d[k].(string); ok && s != "" {
			if raw, err := base64.StdEncoding.DecodeString(s); err == nil {
				d[k] = hex.EncodeToString(raw)
			}
		}
	}
}

func asSlice(v any) []any {
	s, _ := v.([]any)
	return s
}

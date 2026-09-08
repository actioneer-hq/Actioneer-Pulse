package main

import (
	"bytes"
	"compress/gzip"
	"encoding/json"
	"fmt"
	"io"
	"strings"
)

// OTLP payloads are decoded into generic maps so every span/attribute is preserved verbatim for
// re-emission on the wire. We only need to *read* a couple of fields (voice.call_id, traceId,
// parentSpanId) for sharding; everything else round-trips untouched. This mirrors the Python
// frameworks/otlp.py shape (camelCase, AnyValue-boxed attributes).

// errBadBody signals an unreadable OTLP body — the handler maps it to HTTP 400 (not 500), matching
// otlp_payload's ValueError -> HTTPException(400).
type errBadBody struct{ err error }

func (e errBadBody) Error() string { return "unreadable OTLP body: " + e.err.Error() }

// decodePayload turns a request body into the OTLP/JSON dict shape, honoring content-encoding (gzip)
// and content-type (protobuf vs json), matching the substring detection in otlp_payload.
func decodePayload(body []byte, contentType, contentEncoding string) (map[string]any, error) {
	if strings.Contains(strings.ToLower(contentEncoding), "gzip") {
		gunzipped, err := gunzip(body)
		if err != nil {
			return nil, errBadBody{err}
		}
		body = gunzipped
	}
	if strings.Contains(contentType, "protobuf") {
		return decodeProtobuf(body)
	}
	if len(body) == 0 {
		return map[string]any{}, nil
	}
	var payload map[string]any
	if err := json.Unmarshal(body, &payload); err != nil {
		return nil, errBadBody{err}
	}
	return payload, nil
}

func gunzip(b []byte) ([]byte, error) {
	r, err := gzip.NewReader(bytes.NewReader(b))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(r)
}

// gzipJSON marshals v to JSON and gzip-compresses it — the raw-spans record value framing.
// The consumer only decompresses + json.loads, so byte-identical gzip is not required.
func gzipJSON(v any) ([]byte, error) {
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	var buf bytes.Buffer
	w := gzip.NewWriter(&buf)
	if _, err := w.Write(raw); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// ── attribute reading (mirrors otlp.unwrap / attrs_to_dict, string-only) ────────────────────────

// spanAttr returns the stringified value of the given attribute key on a span, or "" if absent.
// Only the scalar AnyValue forms are stringified (that's all sharding needs: voice.call_id).
func spanAttr(span map[string]any, key string) string {
	attrs, _ := span["attributes"].([]any)
	for _, a := range attrs {
		kv, _ := a.(map[string]any)
		if kv == nil {
			continue
		}
		if k, _ := kv["key"].(string); k == key {
			return unwrapString(kv["value"])
		}
	}
	return ""
}

// unwrapString unboxes an AnyValue to its string form, matching how Python's str(unwrap(...)) would
// render the scalar cases we care about. Empty/None -> "".
func unwrapString(v any) string {
	av, _ := v.(map[string]any)
	if av == nil {
		return ""
	}
	if s, ok := av["stringValue"].(string); ok {
		return s
	}
	if b, ok := av["boolValue"].(bool); ok {
		if b {
			return "True" // Python str(True)
		}
		return "False"
	}
	// intValue arrives as a JSON string; doubleValue as a number. Render as-is.
	if s, ok := av["intValue"].(string); ok {
		return s
	}
	if f, ok := av["doubleValue"].(float64); ok {
		return fmt.Sprintf("%v", f)
	}
	return ""
}

// spanStr returns a top-level string field on a span ("" if missing/non-string).
func spanStr(span map[string]any, key string) string {
	s, _ := span[key].(string)
	return s
}

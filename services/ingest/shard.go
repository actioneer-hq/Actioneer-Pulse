package main

import "time"

// outRecord is one raw-spans record to be produced: the partition key, the gzipped-JSON slice value,
// and the string headers. Mirrors the Python produce() output exactly.
type outRecord struct {
	Key     string
	Value   []byte
	Headers map[string]string
}

// shardGroup is one call's spans out of one OTLP batch, plus the resource that introduced it.
type shardGroup struct {
	key      string
	resource any
	spans    []any
}

// shard groups spans into calls: key = span attr voice.call_id if truthy, else the span's traceId,
// else "". Preserves first-seen key order (seq depends on it) and keeps the resource of the first
// resourceSpans block that introduced each key (Python setdefault semantics). Mirrors ingestion.shard.
func shard(payload map[string]any) []shardGroup {
	order := []string{}
	byKey := map[string]*shardGroup{}
	resourceSpans, _ := payload["resourceSpans"].([]any)
	for _, rsAny := range resourceSpans {
		rs, _ := rsAny.(map[string]any)
		if rs == nil {
			continue
		}
		resource := rs["resource"] // may be nil; preserved as-is
		scopeSpans, _ := rs["scopeSpans"].([]any)
		for _, scAny := range scopeSpans {
			sc, _ := scAny.(map[string]any)
			if sc == nil {
				continue
			}
			spans, _ := sc["spans"].([]any)
			for _, spanAny := range spans {
				span, _ := spanAny.(map[string]any)
				if span == nil {
					continue
				}
				key := spanAttr(span, callIDAttr)
				if key == "" {
					key = spanStr(span, "traceId")
				}
				g := byKey[key]
				if g == nil {
					g = &shardGroup{key: key, resource: resource}
					byKey[key] = g
					order = append(order, key)
				}
				g.spans = append(g.spans, span)
			}
		}
	}
	out := make([]shardGroup, 0, len(order))
	for _, k := range order {
		out = append(out, *byKey[k])
	}
	return out
}

const callIDAttr = "voice.call_id"

// buildRecords shards a payload and builds the per-call records: one batchID per call to buildRecords,
// seq = the enumeration index over shard groups *including* skipped empty groups (so surviving seqs
// can be non-contiguous), key = shardKey||traceID||batchID. Mirrors ingestion.produce, minus the send.
func buildRecords(payload map[string]any, org, agentID, batchID string, now time.Time) ([]outRecord, error) {
	groups := shard(payload)
	recvAt := isoMicros(now)
	records := make([]outRecord, 0, len(groups))
	for seq, g := range groups {
		if len(g.spans) == 0 {
			continue // seq still advanced by the loop index, matching enumerate() over all groups
		}
		traceID := firstTraceID(g.spans)
		value, err := gzipJSON(sliceEnvelope(g.resource, g.spans))
		if err != nil {
			return nil, err
		}
		records = append(records, outRecord{
			Key:   firstNonEmpty(g.key, traceID, batchID),
			Value: value,
			Headers: map[string]string{
				"org":         org,
				"agent_id":    agentID,
				"shard_key":   g.key,
				"trace_id":    traceID,
				"batch_id":    batchID,
				"seq":         itoa(seq),
				"received_at": recvAt,
			},
		})
	}
	return records, nil
}

// sliceEnvelope is the wire value's JSON structure: one resourceSpans entry, one scopeSpans entry,
// all the call's spans flattened into it. Mirrors ingestion._slice_bytes.
func sliceEnvelope(resource any, spans []any) map[string]any {
	if resource == nil {
		resource = map[string]any{}
	}
	return map[string]any{
		"resourceSpans": []any{
			map[string]any{
				"resource":   resource,
				"scopeSpans": []any{map[string]any{"spans": spans}},
			},
		},
	}
}

func firstTraceID(spans []any) string {
	for _, s := range spans {
		if span, ok := s.(map[string]any); ok {
			if t := spanStr(span, "traceId"); t != "" {
				return t
			}
		}
	}
	return ""
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

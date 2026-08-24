// Mirrors what read.py returns. Both endpoints reflect over their table, so the
// optional-everything shape is deliberate: a column the worker has not filled yet
// arrives as null rather than going missing.
export type Call = {
  id: string;
  source: string;
  environment: string;
  status: string;
  duration_s: number | null;
  started_at: string | null;
  turns: number;
  labels: Record<string, string>;
};

export type CallHeader = Call & {
  engine: string | null;
  carrier: string | null;
  llm_provider: string | null;
  tts_provider: string | null;
  stt_provider: string | null;
  voice: string | null;
  metric_version: number | null;
};

export type Turn = {
  turn_index: number;
  turn_id: string | null;
  trigger: string | null;
  interrupted: boolean | null;
  abandoned: boolean | null;
  endpointing_ms: number | null;
  stt_lag_ms: number | null;
  llm_ttft_ms: number | null;
  tts_ttfb_ms: number | null;
  response_latency_ms: number | null;
  language: string | null;
  stt_confidence: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cut_reason: string | null;
  caller_transcript: string | null;
  llm_raw: string | null;
  llm_spoken: string | null;
};

export type SpanEvent = {
  name: string | null;
  t_offset_s: number;
  attrs: Record<string, unknown>;
  content_text: string | null;
};

export type Span = {
  span_id: string;
  parent_span_id: string | null;
  name: string | null;
  stage: Stage;
  turn_id: string | null;
  t_start_s: number;
  duration_s: number | null;
  attrs: Record<string, unknown>;
  content_text: string | null;
  content_kind: string | null;
  events: SpanEvent[];
};

export type Stage =
  | "call" | "turn" | "speech" | "stt" | "llm"
  | "tts" | "playout" | "tool" | "net" | "unknown";

export const STAGES: Stage[] = [
  "call", "turn", "speech", "stt", "llm", "tts", "playout", "tool", "net", "unknown",
];

export type CallDetail = {
  call: CallHeader;
  turns: Turn[];
  metrics: { name: string; value: number | string | null; available: boolean }[];
  trust: { spans_complete: boolean; media_ready: boolean };
};

export type Trace = {
  call_id: string;
  source: string;
  duration_s: number | null;
  spans: Span[];
};

async function get<T>(path: string): Promise<T> {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json() as Promise<T>;
}

export const listCalls = (limit = 200) =>
  get<{ items: Call[] }>(`/v1/calls?limit=${limit}`).then((d) => d.items);
export const getCall = (id: string) => get<CallDetail>(`/v1/calls/${id}`);
export const getTrace = (id: string) => get<Trace>(`/v1/calls/${id}/spans`);

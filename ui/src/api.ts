// Mirrors what read.py returns. Both endpoints reflect over their table, so the
// optional-everything shape is deliberate: a column the worker has not filled yet
// arrives as null rather than going missing.
export type Call = {
  id: string;
  source: string;
  environment: string;
  status: string;
  media_ready: boolean;
  analysed: boolean;
  duration_s: number | null;
  started_at: string | null;
  turns: number;
  barge_ins: number;
  p50_v2v_ms: number | null;
  labels: Record<string, string>;
};

export type CallHeader = Omit<Call, "turns" | "barge_ins" | "p50_v2v_ms" | "analysed"> & {
  engine: string | null;
  carrier: string | null;
  llm_provider: string | null;
  tts_provider: string | null;
  stt_provider: string | null;
  voice: string | null;
  campaign_id: string | null;
  channel_map: Record<string, string> | null;
  sample_rate: number | null;
  terminal_reason: string | null;
  hangup_by: string | null;
  cost_total: number | null;
  cost_currency: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  span_dropped_events: number | null;
  unattributed_spans: number | null;
  spans_complete: boolean;
  metric_version: number | null;
  adapter_version: number | null;
  app_version: string | null;
};

export type Turn = {
  turn_index: number;
  turn_id: string | null;
  trigger: string | null;
  interrupted: boolean | null;
  abandoned: boolean | null;
  stt_final_at: number | null;
  committed_at: number | null;
  caller_utt_end_s: number | null;
  agent_utt_start_s: number | null;
  tts_first_audio_at: number | null;
  tts_start_at: number | null;
  llm_first_token_at: number | null;
  response_latency_ms: number | null;
  endpointing_ms: number | null;
  stt_lag_ms: number | null;
  llm_ttft_ms: number | null;
  assembly_ms: number | null;
  tts_ttfb_ms: number | null;
  unattributed_ms: number | null;
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

export type Audio = {
  url: string | null;
  sample_rate: number | null;
  channels: number | null;
  duration_s: number | null;
};

export type Trust = {
  spans_complete: boolean;
  media_ready: boolean;
  capture_coverage: Record<string, number> | number[] | Record<string, never>;
  span_dropped_events: number | null;
  unattributed_spans: number | null;
};

// One consolidated payload — header, turns, metrics, trust, the span tree, waveform
// peaks (base64 per channel), and a presigned audio URL. One round trip.
export type CallDetail = {
  call: CallHeader;
  turns: Turn[];
  metrics: { name: string; value: number | string | null; available: boolean }[];
  trust: Trust;
  spans: Span[];
  peaks: Record<string, string>;
  audio: Audio | null;
};

// The span sub-view Waterfall renders; built from CallDetail, not fetched.
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
export const getCall = (id: string) => get<CallDetail>(`/v1/calls/${encodeURIComponent(id)}`);

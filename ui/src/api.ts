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
  analysis_mode: "full" | "audio-only" | "diarized" | null;
  analysis_error: string | null;
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
  dispatch_ms: number | null;
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
  audio_analysis: boolean;
  capture_coverage: Record<string, number> | number[] | Record<string, never>;
  span_dropped_events: number | null;
  unattributed_spans: number | null;
};

// One consolidated payload — header, turns, metrics, trust, the span tree, waveform
// peaks (base64 per channel), and a presigned audio URL. One round trip.
export type Discrepancy = {
  turn_index: number | null;
  dimension: string;
  field: string;
  reported: string | null;
  measured: string | null;
  delta: number | null;
  band: number | null;
  verdict: string;
  note: string | null;
};

export type Judgment = {
  disposition: string | null;
  status: string | null;
  model: string | null;
  sentiment: string | null;
  objective_achieved: string | null;
  answered_by: string | null;
  primary_language: string | null;
  secondary_languages: string[] | null;
  script_adherence: string | null;
  escalation_requested: boolean | null;
  callback_requested: boolean | null;
  callback_time: string | null;
  guardrail_violation: boolean | null;
  guardrail_violation_points: string[] | null;
  is_failure: boolean | null;
  root_cause: string | null;
  model_fault: string | null;  // none|asr|llm|tts|other
  model_fault_detail: string | null;
  hallucination: boolean | null;
  hallucination_detail: string | null;
  suggested_fix: string | null;
  summary: string | null;
};

export type CallDetail = {
  call: CallHeader;
  turns: Turn[];
  metrics: { name: string; value: number | string | null; available: boolean }[];
  trust: Trust;
  spans: Span[];
  peaks: Record<string, string>;
  audio: Audio | null;
  discrepancies: Discrepancy[];
  judgment: Judgment | null;
  script: { sha256: string | null; version: number | null; created_by: string | null } | null;
};

// The span sub-view Waterfall renders; built from CallDetail, not fetched.
export type Trace = {
  call_id: string;
  source: string;
  duration_s: number | null;
  spans: Span[];
};

// ---- identity types (mirror src/voiceobs/api/{auth,orgs,agents}.py) ----
export type AuthConfig = {
  dev_open: boolean;
  signup_open: boolean;
  dev_email: string | null;
  dev_password: string | null;
};
export type Role = "owner" | "admin" | "member" | "viewer";
export type Membership = { org_id: string; org_name: string | null; role: Role };
export type Me = {
  user: { id: string; email: string; name: string | null };
  memberships: Membership[];
};
export type Agent = { id: string; name: string; slug: string; org_id: string };
// A credential input the UI renders dynamically (from the wizard/default field-spec).
export type CredField = { name: string; label: string; type: string; secret: boolean };
// Sent to the server. `credentials` secret values are write-only (omit to keep the stored one).
export type AudioConfigIn = {
  enabled: boolean;
  provider?: string;                         // 's3_compatible' | 'azure'
  descriptor?: Record<string, unknown>;      // where/how to fetch
  cred_spec?: CredField[];                    // the credential form
  credentials?: Record<string, string>;      // { name: value }
  // BYO diarization endpoint for mixed/mono recordings (write-only key).
  diarize_base_url?: string | null;
  diarize_model?: string | null;
  diarize_api_key?: string | null;
};
// Returned by the server — never includes secret values, only which secrets are stored.
export type AudioConfig = {
  enabled: boolean;
  provider: string | null;
  descriptor: Record<string, unknown> | null;
  cred_spec: CredField[] | null;
  cred_public: Record<string, string>;
  has_secret: Record<string, boolean>;
  diarize_base_url?: string | null;
  diarize_model?: string | null;
  has_diarize_key?: boolean;
};
export type IngestTokenRow = {
  id: string;
  prefix: string;
  name: string | null;
  revoked: boolean;
  last_used_at: string | null;
};
export type MintedToken = { id: string; token: string; prefix: string };
export type Member = {
  membership_id: string;
  user_id: string;
  email: string | null;
  role: Role;
};

// The active org rides on X-Voiceobs-Org; it only *selects among* the caller's own orgs
// server-side, so it can never widen access. The AuthProvider keeps this in sync.
let activeOrg: string | null = null;
export const setApiOrg = (org: string | null) => { activeOrg = org; };

// A 401 that even a refresh can't fix means the session is truly gone; bounce to /login.
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

// Double-submit CSRF: echo the readable vo_csrf cookie back as a header on unsafe requests.
function csrfToken(): string | null {
  const m = document.cookie.match(/(?:^|;\s*)vo_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

async function rawFetch(method: Method, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  if (activeOrg) headers["X-Voiceobs-Org"] = activeOrg;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return fetch(path, {
    method,
    credentials: "include",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

// One in-flight refresh shared by all concurrent 401s, so a burst triggers a single rotate.
let refreshing: Promise<boolean> | null = null;
function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = rawFetch("POST", "/v1/auth/refresh")
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function req<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let r = await rawFetch(method, path, body);
  // Access JWT likely expired → refresh once, then retry the original request.
  if (r.status === 401 && path !== "/v1/auth/refresh") {
    if (await tryRefresh()) r = await rawFetch(method, path, body);
  }
  if (r.status === 401) {
    onUnauthorized?.();
    throw new Error("unauthorized");
  }
  if (!r.ok) {
    const detail = await r.json().catch(() => null);
    throw new Error(detail?.detail ?? `${path} -> ${r.status}`);
  }
  return (r.status === 204 ? undefined : await r.json()) as T;
}

const get = <T>(path: string) => req<T>("GET", path);

// ---- auth ----
export const getAuthConfig = () => get<AuthConfig>("/v1/auth/config");
export const login = (email: string, password: string, org = "default") =>
  req<{ user: Me["user"] }>("POST", "/v1/auth/login", { email, password, org });
export const signup = (email: string, password: string, org_name?: string, name?: string) =>
  req("POST", "/v1/auth/signup", { email, password, org_name, name });
export const acceptInvite = (token: string, password: string, name?: string) =>
  req("POST", "/v1/auth/accept-invite", { token, password, name });
export const logout = () => req("POST", "/v1/auth/logout");
export const logoutEverywhere = () => req("POST", "/v1/auth/logout-all");
export const getMe = () => get<Me>("/v1/auth/me");

// ---- agents + ingest tokens ----
export const listAgents = () => get<{ items: Agent[] }>("/v1/agents").then((d) => d.items);
export type AgentScript = {
  version: number | null;
  sha256?: string | null;
  text?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  active?: boolean;
};

export const createAgent = (
  name: string, audio?: AudioConfigIn, script?: string, guardrails?: string,
) => req<Agent>("POST", "/v1/agents", { name, audio, script, guardrails });
export const getAgentScript = (agentId: string) =>
  req<AgentScript>("GET", `/v1/agents/${agentId}/script`);
export const setAgentScript = (agentId: string, text: string) =>
  req<AgentScript>("PUT", `/v1/agents/${agentId}/script`, { text });
export const listAgentScripts = (agentId: string) =>
  req<{ items: AgentScript[] }>("GET", `/v1/agents/${agentId}/scripts`).then((d) => d.items);

// guardrails mirror scripts (versioned NLI rules)
export type AgentGuardrails = AgentScript;
export const getAgentGuardrails = (agentId: string) =>
  req<AgentGuardrails>("GET", `/v1/agents/${agentId}/guardrails`);
export const setAgentGuardrails = (agentId: string, text: string) =>
  req<AgentGuardrails>("PUT", `/v1/agents/${agentId}/guardrails`, { text });
export const listAgentGuardrails = (agentId: string) =>
  req<{ items: AgentGuardrails[] }>("GET", `/v1/agents/${agentId}/guardrails/versions`)
    .then((d) => d.items);
export const getAudioConfig = (agentId: string) =>
  req<AudioConfig>("GET", `/v1/agents/${agentId}/audio-config`);
export const setAudioConfig = (agentId: string, cfg: AudioConfigIn) =>
  req<AudioConfig>("PUT", `/v1/agents/${agentId}/audio-config`, cfg);
export const renameAgent = (id: string, name: string) =>
  req<Agent>("PATCH", `/v1/agents/${id}`, { name });
export const deleteAgent = (id: string) => req("DELETE", `/v1/agents/${id}`);
export const listTokens = (agentId: string) =>
  get<{ items: IngestTokenRow[] }>(`/v1/agents/${agentId}/ingest-tokens`).then((d) => d.items);
export const mintToken = (agentId: string, name?: string) =>
  req<MintedToken>("POST", `/v1/agents/${agentId}/ingest-tokens`, { name });
export const rotateToken = (agentId: string, tid: string) =>
  req<MintedToken>("POST", `/v1/agents/${agentId}/ingest-tokens/${tid}/rotate`);
export const revokeToken = (agentId: string, tid: string) =>
  req("DELETE", `/v1/agents/${agentId}/ingest-tokens/${tid}`);

// ---- orgs + members ----
export const listMembers = (orgId: string) =>
  get<{ items: Member[] }>(`/v1/orgs/${orgId}/members`).then((d) => d.items);
export const addMember = (orgId: string, email: string, role: Role) =>
  req<{ invite_token: string | null }>("POST", `/v1/orgs/${orgId}/members`, { email, role });
export const setRole = (orgId: string, mid: string, role: Role) =>
  req("PATCH", `/v1/orgs/${orgId}/members/${mid}`, { role });
export const removeMember = (orgId: string, mid: string) =>
  req("DELETE", `/v1/orgs/${orgId}/members/${mid}`);
export const setAgentAccess = (orgId: string, mid: string, agent_ids: string[]) =>
  req("PUT", `/v1/orgs/${orgId}/members/${mid}/agent-access`, { agent_ids });

// ---- chat ----
export type ChatStep = { name: string; args?: unknown; summary: string };
export type ChatMsg = { role: "user" | "assistant"; content: string; steps: ChatStep[] };
export type Conversation = { id: string; title: string; updated_at?: string };
export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "tool_call"; name: string; args: unknown }
  | { type: "tool_result"; name: string; summary: string }
  | { type: "done"; content: string; steps: ChatStep[] }
  | { type: "error"; error: string };

export const listConversations = () =>
  get<{ items: Conversation[] }>("/v1/chat/conversations").then((d) => d.items);
export const createConversation = () =>
  req<{ id: string; title: string }>("POST", "/v1/chat/conversations");
export const getConversation = (id: string) =>
  get<{ id: string; title: string; messages: ChatMsg[] }>(`/v1/chat/conversations/${id}`);
export const deleteConversation = (id: string) =>
  req("DELETE", `/v1/chat/conversations/${id}`);

/** POST a message and stream the agent's SSE events to `onEvent`. Hand-rolled reader because
 *  EventSource can't POST a body / send our cookies+CSRF. Shared by global + per-call chat. */
async function _streamSSE(url: string, text: string, onEvent: (e: ChatEvent) => void): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (activeOrg) headers["X-Voiceobs-Org"] = activeOrg;
  const csrf = csrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const r = await fetch(url, {
    method: "POST", credentials: "include", headers, body: JSON.stringify({ text }),
  });
  if (r.status === 401) { onUnauthorized?.(); throw new Error("unauthorized"); }
  if (!r.body) throw new Error("no stream");
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const chunks = buf.split("\n\n");
    buf = chunks.pop() ?? "";  // keep the incomplete tail
    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (line) onEvent(JSON.parse(line.slice(5).trim()) as ChatEvent);
    }
  }
}

export const streamChat = (id: string, text: string, onEvent: (e: ChatEvent) => void) =>
  _streamSSE(`/v1/chat/conversations/${id}/stream`, text, onEvent);

// ---- per-call chat (scoped to one call) ----
export const getCallChat = (callId: string) =>
  get<{ id: string; messages: ChatMsg[] }>(`/v1/calls/${encodeURIComponent(callId)}/chat`);
export const streamCallChat = (callId: string, text: string, onEvent: (e: ChatEvent) => void) =>
  _streamSSE(`/v1/calls/${encodeURIComponent(callId)}/chat/stream`, text, onEvent);

// ---- boards (BI dashboard metrics) ----
export type BoardFilters = { agent_id?: string; environment?: string; range: string };
export type BoardSnapshot = {
  range: string;
  bucket_s: number;
  buckets: string[];  // ISO timestamps, the x-axis
  volume: number[];
  failure: { failed: number[]; total: number[]; rate: number[] };
  latency: { p50: (number | null)[]; p95: (number | null)[] };
  guardrail: { violations: number[]; judged: number[]; rate: number[] };
  tools: { calls: number[]; errors: number[]; rate: number[] };
  cost: { total: number[]; llm: number[]; stt: number[]; tts: number[] };
  disposition: Record<string, number>;
  totals: {
    calls: number; failure_rate: number; p50_ms: number | null; p95_ms: number | null;
    cost_total: number; violation_rate: number; tool_calls: number; tool_error_rate: number;
  };
};

const boardQuery = (f: BoardFilters) => {
  const p = new URLSearchParams({ range: f.range });
  if (f.agent_id) p.set("agent_id", f.agent_id);
  if (f.environment) p.set("environment", f.environment);
  return p.toString();
};

export const getBoardsSummary = (f: BoardFilters) =>
  get<BoardSnapshot>(`/v1/boards/summary?${boardQuery(f)}`);

/** Open the live board SSE and call `onSnapshot` on each pushed snapshot. Returns an abort fn.
 *  Hand-rolled reader (same reason as streamChat: cookies + org header on a stream). */
export function streamBoards(
  f: BoardFilters, onSnapshot: (s: BoardSnapshot) => void, onError?: () => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    const headers: Record<string, string> = {};
    if (activeOrg) headers["X-Voiceobs-Org"] = activeOrg;
    try {
      const r = await fetch(`/v1/boards/stream?${boardQuery(f)}`,
        { credentials: "include", headers, signal: ctrl.signal });
      if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split("\n\n");
        buf = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === "snapshot") onSnapshot(ev.data as BoardSnapshot);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") onError?.();
    }
  })();
  return () => ctrl.abort();
}

// ---- clusters (semantic clustering of analysis prose) ----
export const CLUSTER_LEVERS: [string, string][] = [
  ["root_cause", "Failure themes"],
  ["suggested_fix", "Fix backlog"],
  ["summary", "Caller intents"],
  ["guardrail_points", "Guardrail breaches"],
  ["hallucination_detail", "Hallucinations"],
];
export type ClusterFilters = { agent_id?: string; range?: string };
export type ClusterInfo = { key: number; label: string | null; size: number };
export type ClusterPoint = { call_id: string; x: number; y: number; cluster_key: number | null };
export type ClusterView = { lever: string; clusters: ClusterInfo[]; points: ClusterPoint[] };
export type Archetype = {
  combo: Record<string, string>; count: number;
  cause_total: number; consistency: number | null; lift: number | null;
};
export type ArchetypeView = { dims: string[]; total: number; archetypes: Archetype[] };

const clusterQuery = (f: ClusterFilters) => {
  const p = new URLSearchParams();
  if (f.range) p.set("range", f.range);
  if (f.agent_id) p.set("agent_id", f.agent_id);
  return p.toString();
};
export const getClusters = (lever: string, f: ClusterFilters) =>
  get<ClusterView>(`/v1/clusters/${lever}?${clusterQuery(f)}`);
export const getArchetypes = (f: ClusterFilters, minCount = 2) =>
  get<ArchetypeView>(`/v1/clusters/archetypes?${clusterQuery(f)}&min_count=${minCount}`);

// ---- calls (now scoped server-side by the session + active org) ----
export const listCalls = (limit = 200, agentId?: string) =>
  get<{ items: Call[] }>(
    `/v1/calls?limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""}`,
  ).then((d) => d.items);
export const getCall = (id: string) => get<CallDetail>(`/v1/calls/${encodeURIComponent(id)}`);

// ---- backfill (analyse historical audio from storage) ----
export type BackfillPreview = {
  agent_id: string;
  audio_calls: number;
  files: number;
  sample_call_ids: string[];
};
export type BackfillJob = {
  id: string;
  agent_id: string;
  source: string | null;
  status: "queued" | "scanning" | "running" | "clustering" | "done" | "failed" | "cancelled";
  phase: string | null;
  total: number;
  completed: number;
  failed: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
};
// The SSE union pushed by GET /v1/backfill/{id}/events (mirrors ChatEvent's style).
export type BackfillEvent =
  | { type: "progress"; data: BackfillJob }
  | { type: "call-analyzed"; data: Call }
  | { type: "boards-refresh" }
  | { type: "done"; data: BackfillJob }
  | { type: "error"; error: string };

export const backfillPreview = (agentId: string) =>
  get<BackfillPreview>(`/v1/backfill/preview?agent_id=${encodeURIComponent(agentId)}`);
export const createBackfill = (
  body: { agent_id: string; source?: string; options?: Record<string, unknown> },
) => req<BackfillJob>("POST", "/v1/backfill", body);
export const getBackfillJob = (id: string) =>
  get<BackfillJob>(`/v1/backfill/${encodeURIComponent(id)}`);
export const cancelBackfill = (id: string) =>
  req<BackfillJob>("POST", `/v1/backfill/${encodeURIComponent(id)}/cancel`);

/** Open the backfill SSE and call `onEvent` for each pushed event. Returns a stop fn.
 *  Hand-rolled reader, modelled on streamBoards (cookies + org header on a GET stream). */
export function streamBackfill(
  id: string, onEvent: (e: BackfillEvent) => void, onError?: () => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    const headers: Record<string, string> = {};
    if (activeOrg) headers["X-Voiceobs-Org"] = activeOrg;
    try {
      const r = await fetch(`/v1/backfill/${encodeURIComponent(id)}/events`,
        { credentials: "include", headers, signal: ctrl.signal });
      if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split("\n\n");
        buf = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data:"));
          if (!line) continue;
          onEvent(JSON.parse(line.slice(5).trim()) as BackfillEvent);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") onError?.();
    }
  })();
  return () => ctrl.abort();
}

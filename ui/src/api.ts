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
// Sent to the server (secret_access_key write-only). All fields optional so partial edits work.
export type AudioConfigIn = {
  enabled: boolean;
  s3_bucket?: string;
  s3_prefix?: string;
  s3_region?: string;
  s3_endpoint_url?: string;
  access_key_id?: string;
  secret_access_key?: string;
};
// Returned by the server — never includes the secret, only has_secret.
export type AudioConfig = Omit<AudioConfigIn, "secret_access_key"> & { has_secret: boolean };
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
export const login = (email: string, password: string) =>
  req<{ user: Me["user"] }>("POST", "/v1/auth/login", { email, password });
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
 *  EventSource can't POST a body / send our cookies+CSRF. */
export async function streamChat(
  id: string, text: string, onEvent: (e: ChatEvent) => void,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (activeOrg) headers["X-Voiceobs-Org"] = activeOrg;
  const csrf = csrfToken();
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const r = await fetch(`/v1/chat/conversations/${id}/stream`, {
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

// ---- calls (now scoped server-side by the session + active org) ----
export const listCalls = (limit = 200, agentId?: string) =>
  get<{ items: Call[] }>(
    `/v1/calls?limit=${limit}${agentId ? `&agent_id=${encodeURIComponent(agentId)}` : ""}`,
  ).then((d) => d.items);
export const getCall = (id: string) => get<CallDetail>(`/v1/calls/${encodeURIComponent(id)}`);

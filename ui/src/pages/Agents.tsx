import { useCallback, useEffect, useRef, useState } from "react";
import {
  backfillPreview,
  createAgent,
  deleteAgent,
  getAgentGuardrails,
  getAgentScript,
  getAudioConfig,
  listAgentGuardrails,
  listAgents,
  listAgentScripts,
  listCalls,
  listTokens,
  mintToken,
  renameAgent,
  revokeToken,
  rotateToken,
  setAgentGuardrails,
  setAgentScript,
  setAudioConfig,
  type Agent,
  type AgentGuardrails,
  type AgentScript,
  type AudioConfig,
  type CredField,
  type IngestTokenRow,
  type BackfillPreview,
  type MintedToken,
} from "../api";
import { useAuth } from "../auth";
import { useBackfill } from "../BackfillProvider";

// Producer frameworks offered at agent creation. Only LiveKit is wired up today; the rest
// are shown disabled so the choice is explicit and the roadmap is visible.
const FRAMEWORKS: { id: string; label: string; note: string; ready: boolean }[] = [
  { id: "livekit", label: "LiveKit", note: "LiveKit Agents — native OTLP", ready: true },
  { id: "byo", label: "Bring your own OTLP", note: "Any OpenTelemetry producer", ready: false },
];

export default function Agents() {
  const { activeOrg } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listAgents().then((a) => {
      setAgents(a);
      setSel((cur) => (a.some((x) => x.id === cur) ? cur : a[0]?.id ?? null));
    }).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load, activeOrg]);

  async function add(name: string, script?: string, guardrails?: string, audio?: boolean) {
    setError(null);
    try {
      const a = await createAgent(name.trim(), audio ? { enabled: true } : undefined, script, guardrails);
      setCreating(false);
      load();
      setSel(a.id);
    } catch (e) { setError((e as Error).message); }
  }

  async function rename(a: Agent) {
    const name = prompt("Rename agent", a.name)?.trim();
    if (name && name !== a.name) { await renameAgent(a.id, name); load(); }
  }

  async function remove(a: Agent) {
    if (!confirm(`Delete agent "${a.name}"? Its ingest tokens stop working.`)) return;
    await deleteAgent(a.id);
    load();
  }

  const selected = agents.find((a) => a.id === sel) ?? null;

  return (
    <div className="settings">
      <div className="settings-hd">
        <h1>Agents</h1>
        <div className="sub">An agent is a project / OTLP routing target. Producers authenticate
          with a per-agent ingest token.</div>
      </div>
      {error && <div className="auth-error">{error}</div>}
      <div className="settings-cols">
        <div className="col">
          <div className="add-row">
            <button className="btn-primary" onClick={() => setCreating(true)}>+ New agent</button>
          </div>
          <table>
            <tbody>
              {agents.map((a) => (
                <tr key={a.id} className={a.id === sel ? "on" : undefined}
                  onClick={() => setSel(a.id)}>
                  <td>
                    <div className="strong">{a.name}</div>
                    <div className="mono dimtxt">{a.slug}</div>
                  </td>
                  <td className="r">
                    <button className="link" onClick={(e) => { e.stopPropagation(); rename(a); }}>
                      Rename</button>
                    <button className="link bad" onClick={(e) => { e.stopPropagation(); remove(a); }}>
                      Delete</button>
                  </td>
                </tr>
              ))}
              {agents.length === 0 && (
                <tr><td className="dimtxt">No agents yet — add one to start ingesting.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="col">
          {selected
            ? <AgentDetail agent={selected} />
            : <div className="empty">Select an agent to connect it and manage ingest tokens.</div>}
        </div>
      </div>
      {creating && <NewAgentModal onClose={() => setCreating(false)} onCreate={add} />}
    </div>
  );
}

function NewAgentModal(
  { onClose, onCreate }:
  { onClose: () => void;
    onCreate: (name: string, script?: string, guardrails?: string, audio?: boolean) => void },
) {
  const [name, setName] = useState("");
  const [framework, setFramework] = useState("livekit");
  const [script, setScript] = useState("");
  const [guardrails, setGuardrails] = useState("");
  const [audio, setAudio] = useState(false);

  function submit() {
    if (!name.trim()) return;
    onCreate(name, script.trim() || undefined, guardrails.trim() || undefined, audio);
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal wide" onClick={(e) => e.stopPropagation()}>
        <h3>New agent</h3>
        <p className="sub">An agent is a project / OTLP routing target. Pick the framework your
          voice agent runs on, then connect it with an ingest token.</p>
        <div className="field">
          <label htmlFor="agent-name">Name</label>
          <input id="agent-name" autoFocus value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sales Bot" />
        </div>
        <div className="field">
          <label>Framework</label>
          <div className="fw-picker">
            {FRAMEWORKS.map((f) => (
              <button key={f.id} type="button" disabled={!f.ready}
                className={`fw-option ${framework === f.id ? "on" : ""} ${f.ready ? "" : "soon"}`}
                onClick={() => f.ready && setFramework(f.id)}>
                <span className="fw-name">{f.label}{!f.ready && <em> · coming soon</em>}</span>
                <span className="fw-note">{f.note}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label htmlFor="agent-script">Script <span className="dimtxt">— the prompt this agent
            follows (optional; versioned & hashed)</span></label>
          <textarea id="agent-script" className="script-area" value={script}
            onChange={(e) => setScript(e.target.value)} rows={4}
            placeholder="e.g. You are a scheduling assistant. Confirm the appointment, then…" />
        </div>

        <div className="field">
          <label htmlFor="agent-guardrails">Guardrails <span className="dimtxt">— rules the agent
            must obey, one per line (optional; versioned & hashed)</span></label>
          <textarea id="agent-guardrails" className="script-area" value={guardrails}
            onChange={(e) => setGuardrails(e.target.value)} rows={4}
            placeholder={"e.g.\nStay on script; don't be steered off purpose.\nAlways verify the caller before any DB/tool lookup."} />
        </div>

        <div className="field">
          <label className="check">
            <input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} />
            <span>Enable audio analysis <span className="dimtxt">— analyse call recordings (tone,
              dead-air, talk ratio). You can toggle this anytime.</span></span>
          </label>
          <p className="dimtxt">Where recordings live (S3/Azure) is configured after creation in the
            Storage panel.</p>
        </div>

        <div className="modal-foot">
          <button className="link" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!name.trim()} onClick={submit}>
            Create agent</button>
        </div>
      </div>
    </div>
  );
}

function AgentDetail({ agent }: { agent: Agent }) {
  const [tokens, setTokens] = useState<IngestTokenRow[]>([]);
  // The last plaintext token from this session's mint/rotate — the only time we ever see it.
  // Shared so the Connect snippet can show a real Bearer header, then management can revoke it.
  const [minted, setMinted] = useState<MintedToken | null>(null);
  const [name, setName] = useState("");

  const load = useCallback(() => { listTokens(agent.id).then(setTokens).catch(() => setTokens([])); },
    [agent.id]);
  useEffect(() => { load(); setMinted(null); }, [load]);

  async function mint() {
    setMinted(await mintToken(agent.id, name.trim() || undefined));
    setName("");
    load();
  }
  async function rotate(t: IngestTokenRow) {
    setMinted(await rotateToken(agent.id, t.id));
    load();
  }
  async function revoke(t: IngestTokenRow) {
    if (!confirm("Revoke this token? Producers using it stop working immediately.")) return;
    await revokeToken(agent.id, t.id);
    load();
  }

  return (
    <>
      <ScriptPanel agent={agent} />
      <GuardrailsPanel agent={agent} />
      <StoragePanel agent={agent} />
      <ConnectPanel agent={agent} token={minted?.token ?? null} onMint={mint} />
      <div className="panel-card">
        <h3>Ingest tokens · {agent.name}</h3>
        {minted && (
          <div className="minted">
            <div className="minted-hd">Copy this token now — it is shown only once.</div>
            <code className="mono">{minted.token}</code>
            <button className="link" onClick={() => navigator.clipboard?.writeText(minted.token)}>
              Copy</button>
          </div>
        )}
        <div className="add-row">
          <input value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && mint()} placeholder="Label (e.g. prod)…" />
          <button className="btn-primary" onClick={mint}>Mint token</button>
        </div>
        <table>
          <thead>
            <tr><th>Prefix</th><th>Label</th><th>Last used</th><th></th></tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id} className={t.revoked ? "revoked" : undefined}>
                <td className="mono">{t.prefix}…{t.revoked && <span className="pill bad">revoked</span>}</td>
                <td>{t.name ?? "—"}</td>
                <td className="dimtxt">{t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never"}</td>
                <td className="r">
                  {!t.revoked && <>
                    <button className="link" onClick={() => rotate(t)}>Rotate</button>
                    <button className="link bad" onClick={() => revoke(t)}>Revoke</button>
                  </>}
                </td>
              </tr>
            ))}
            {tokens.length === 0 && <tr><td colSpan={4} className="dimtxt">No tokens yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}

// Default credential field-specs for manual setup (no wizard). A wizard-supplied cred_spec fully
// overrides these — the form renders whatever spec is in effect, so any provider/store works.
const DEFAULT_SPECS: Record<string, CredField[]> = {
  s3_compatible: [
    { name: "access_key_id", label: "Access key ID", type: "text", secret: false },
    { name: "secret_access_key", label: "Secret access key", type: "password", secret: true },
    { name: "region", label: "Region", type: "text", secret: false },
    { name: "endpoint_url", label: "Endpoint (optional, MinIO/R2/…)", type: "text", secret: false },
  ],
  azure: [
    { name: "account_name", label: "Account name", type: "text", secret: false },
    { name: "account_key", label: "Account key", type: "password", secret: true },
  ],
};
// The default convention descriptor for manual setup: <prefix>/<call_id>/<file>.
const DEFAULT_FILE_MAP = {
  "audio.wav": "audio", "audio_caller.wav": "audio_caller", "audio_agent.wav": "audio_agent",
};

// Per-agent blob-storage config. The credential form is DATA-driven (cred_spec) — a future wizard
// pushes the spec + descriptor; here we default to the S3/convention form for manual setup.
function StoragePanel({ agent }: { agent: Agent }) {
  const [cfg, setCfg] = useState<AudioConfig | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [provider, setProvider] = useState("s3_compatible");
  const [bucket, setBucket] = useState("");
  const [prefix, setPrefix] = useState("");
  const [creds, setCreds] = useState<Record<string, string>>({});
  const [diarizeUrl, setDiarizeUrl] = useState("");
  const [diarizeModel, setDiarizeModel] = useState("");
  const [diarizeKey, setDiarizeKey] = useState("");
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setSaved(false); setErr(null); setCreds({}); setDiarizeKey("");
    getAudioConfig(agent.id).then((c) => {
      setCfg(c);
      setEnabled(c.enabled);
      setProvider(c.provider || "s3_compatible");
      setBucket((c.descriptor?.bucket as string) || "");
      setPrefix((c.descriptor?.list_prefix as string) || "");
      setDiarizeUrl(c.diarize_base_url || "");
      setDiarizeModel(c.diarize_model || "");
    }).catch((e: Error) => setErr(e.message));
  }, [agent.id]);

  // Effective field-spec: the server's (wizard-supplied) spec wins; else the provider default.
  const spec = cfg?.cred_spec && cfg.cred_spec.length ? cfg.cred_spec : DEFAULT_SPECS[provider] ?? [];

  async function save() {
    setErr(null);
    // Wizard-supplied descriptor is preserved; manual mode builds the convention descriptor.
    const descriptor = cfg?.descriptor && cfg.cred_spec
      ? { ...cfg.descriptor, bucket, list_prefix: prefix }
      : {
          bucket, list_prefix: prefix,
          key_regex: "(?P<call_id>[^/]+)/[^/]+$", id_group: "call_id",
          id_maps_to: "external_call_id", file_map: DEFAULT_FILE_MAP,
        };
    try {
      const c = await setAudioConfig(agent.id, {
        enabled, provider, descriptor, cred_spec: spec, credentials: creds,
        diarize_base_url: diarizeUrl || null, diarize_model: diarizeModel || null,
        diarize_api_key: diarizeKey || undefined,  // omit to keep the stored key
      });
      setCfg(c); setCreds({}); setDiarizeKey(""); setSaved(true);
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <div className="panel-card">
      <h3>Storage · {agent.name} <span className="right">audio recordings</span></h3>
      <label className="audio-toggle">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span><b>Enable audio analysis</b> — Pulse pulls recordings from your bucket and runs the
          audio-ground-truth overlay. Off = OTLP only.</span>
      </label>
      {enabled && (
        <>
          <div className="grid2">
            <div className="field"><label>Provider</label>
              <select className="agent-filter" value={provider}
                onChange={(e) => { setProvider(e.target.value); setCreds({}); }}>
                <option value="s3_compatible">S3-compatible (S3, MinIO, R2, GCS interop…)</option>
                <option value="azure">Azure Blob</option>
              </select></div>
            <div className="field"><label>{provider === "azure" ? "Container" : "Bucket"}</label>
              <input value={bucket} onChange={(e) => setBucket(e.target.value)}
                placeholder="my-recordings" /></div>
            <div className="field"><label>Prefix</label>
              <input value={prefix} onChange={(e) => setPrefix(e.target.value)}
                placeholder="calls/" /></div>
          </div>
          <div className="grid2">
            {spec.map((f) => (
              <div className="field" key={f.name}><label>{f.label}</label>
                <input type={f.secret ? "password" : "text"}
                  autoComplete={f.secret ? "new-password" : "off"}
                  value={creds[f.name] ?? (f.secret ? "" : (cfg?.cred_public?.[f.name] ?? ""))}
                  onChange={(e) => setCreds((v) => ({ ...v, [f.name]: e.target.value }))}
                  placeholder={f.secret && cfg?.has_secret?.[f.name] ? "•••• stored" : ""} /></div>
            ))}
          </div>
          <div className="backfill-section">
            <div className="dimtxt" style={{ marginBottom: 8 }}>
              <b>Speaker separation (diarization)</b> — bring your own endpoint. Only used for
              mixed/mono recordings; separated stereo needs none.
            </div>
            <div className="grid2">
              <div className="field"><label>Diarization endpoint URL</label>
                <input value={diarizeUrl} onChange={(e) => setDiarizeUrl(e.target.value)}
                  placeholder="https://diarize.example.com" /></div>
              <div className="field"><label>Model</label>
                <input value={diarizeModel} onChange={(e) => setDiarizeModel(e.target.value)}
                  placeholder="pyannote-3.1" /></div>
              <div className="field"><label>API key</label>
                <input type="password" autoComplete="new-password" value={diarizeKey}
                  onChange={(e) => setDiarizeKey(e.target.value)}
                  placeholder={cfg?.has_diarize_key ? "•••• stored" : ""} /></div>
            </div>
          </div>
        </>
      )}
      {err && <div className="auth-error">{err}</div>}
      <div className="add-row wide">
        <button className="btn-primary" onClick={save}>Save storage config</button>
        {saved && <span className="dimtxt" style={{ alignSelf: "center" }}>Saved ✓</span>}
      </div>
      {cfg?.enabled && <BackfillSection agent={agent} />}
    </div>
  );
}

// Scan the agent's bucket for historical audio and analyse it in one pass. Preview first
// (how many calls have audio), then hand off to the app-wide BackfillProvider so the
// progress toast survives navigation.
function BackfillSection({ agent }: { agent: Agent }) {
  const { start, job } = useBackfill();
  const [preview, setPreview] = useState<BackfillPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [stt, setStt] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const running = !!job && job.agent_id === agent.id
    && !["done", "failed", "cancelled"].includes(job.status);

  async function doPreview() {
    setErr(null); setLoading(true); setPreview(null);
    try {
      setPreview(await backfillPreview(agent.id));
    } catch (e) { setErr((e as Error).message); }
    finally { setLoading(false); }
  }

  async function confirm() {
    setErr(null);
    try { await start(agent.id, { stt }); setPreview(null); }
    catch (e) { setErr((e as Error).message); }
  }

  return (
    <div className="backfill-section">
      <div className="strong">Backfill from storage</div>
      <p className="dimtxt">Scan this bucket for historical recordings and analyse any call
        that has audio but hasn't been analysed yet.</p>
      {err && <div className="auth-error">{err}</div>}
      <div className="add-row">
        {!preview && (
          <button className="link" disabled={loading || running} onClick={doPreview}>
            {loading ? "Scanning…" : "Preview backfill"}</button>
        )}
        {preview && (
          <>
            <span className="dimtxt" style={{ alignSelf: "center" }}>
              Found {preview.audio_calls} call{preview.audio_calls === 1 ? "" : "s"} with audio
              ({preview.files} file{preview.files === 1 ? "" : "s"}).
            </span>
            <label className="dimtxt" style={{ alignSelf: "center", display: "flex", gap: 6 }}>
              <input type="checkbox" checked={stt} onChange={(e) => setStt(e.target.checked)} />
              Transcribe with STT (content + judge; costs per minute)
            </label>
            <button className="btn-primary" disabled={running || preview.audio_calls === 0}
              onClick={confirm}>Start backfill</button>
            <button className="link" onClick={() => setPreview(null)}>Cancel</button>
          </>
        )}
        {running && <span className="dimtxt" style={{ alignSelf: "center" }}>Backfill running…</span>}
      </div>
    </div>
  );
}

// The agent's script — the prompt it's meant to follow. Versioned + hash-addressed; each call
// pins the version it ran under. Owner/admin edits (viewers get 403 from the API).
function ScriptPanel({ agent }: { agent: Agent }) {
  const [script, setScript] = useState<AgentScript | null>(null);
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [history, setHistory] = useState<AgentScript[]>([]);
  const [showHist, setShowHist] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    getAgentScript(agent.id).then((s) => {
      setScript(s.version ? s : null);
      setText(s.text ?? "");
      setDirty(false);
    }).catch(() => setScript(null));
    listAgentScripts(agent.id).then(setHistory).catch(() => setHistory([]));
  }, [agent.id]);
  useEffect(() => { load(); setShowHist(false); setSaved(false); }, [load]);

  async function save() {
    await setAgentScript(agent.id, text);
    setSaved(true);
    load();
  }

  return (
    <div className="panel-card">
      <h3>
        Script · {agent.name}
        {script?.version != null && <span className="pill" style={{ marginLeft: 8 }}>
          v{script.version} · {script.sha256?.slice(0, 8)}</span>}
      </h3>
      <textarea className="script-area" rows={6} value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); setSaved(false); }}
        placeholder="No script set. Add the prompt this agent is meant to follow…" />
      <div className="add-row" style={{ marginTop: 8 }}>
        <button className="btn-primary" disabled={!dirty || !text.trim()} onClick={save}>
          {script ? "Save new version" : "Save script"}</button>
        {saved && <span className="dimtxt" style={{ alignSelf: "center" }}>saved ✓</span>}
        {history.length > 0 && (
          <button className="link" style={{ marginLeft: "auto" }}
            onClick={() => setShowHist((v) => !v)}>
            {showHist ? "Hide" : `History (${history.length})`}</button>
        )}
      </div>
      {showHist && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Version</th><th>Script ID</th><th>Changed</th></tr></thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.version}>
                <td>v{h.version}{h.active && <span className="pill ok" style={{ marginLeft: 6 }}>active</span>}</td>
                <td className="mono">{h.sha256?.slice(0, 12)}</td>
                <td className="dimtxt">{h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// The agent's guardrails — natural-language rules it must obey (stay on script, verify the caller
// before tool calls, …). Versioned + hash-addressed like the script. Owner/admin edits.
function GuardrailsPanel({ agent }: { agent: Agent }) {
  const [gr, setGr] = useState<AgentGuardrails | null>(null);
  const [text, setText] = useState("");
  const [dirty, setDirty] = useState(false);
  const [history, setHistory] = useState<AgentGuardrails[]>([]);
  const [showHist, setShowHist] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(() => {
    getAgentGuardrails(agent.id).then((g) => {
      setGr(g.version ? g : null);
      setText(g.text ?? "");
      setDirty(false);
    }).catch(() => setGr(null));
    listAgentGuardrails(agent.id).then(setHistory).catch(() => setHistory([]));
  }, [agent.id]);
  useEffect(() => { load(); setShowHist(false); setSaved(false); }, [load]);

  async function save() {
    await setAgentGuardrails(agent.id, text);
    setSaved(true);
    load();
  }

  return (
    <div className="panel-card">
      <h3>
        Guardrails · {agent.name}
        {gr?.version != null && <span className="pill" style={{ marginLeft: 8 }}>
          v{gr.version} · {gr.sha256?.slice(0, 8)}</span>}
      </h3>
      <textarea className="script-area" rows={6} value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); setSaved(false); }}
        placeholder={"No guardrails set. One rule per line, e.g.\nStay on script; don't be steered off purpose.\nAlways verify the caller before any DB/tool lookup."} />
      <div className="add-row" style={{ marginTop: 8 }}>
        <button className="btn-primary" disabled={!dirty || !text.trim()} onClick={save}>
          {gr ? "Save new version" : "Save guardrails"}</button>
        {saved && <span className="dimtxt" style={{ alignSelf: "center" }}>saved ✓</span>}
        {history.length > 0 && (
          <button className="link" style={{ marginLeft: "auto" }}
            onClick={() => setShowHist((v) => !v)}>
            {showHist ? "Hide" : `History (${history.length})`}</button>
        )}
      </div>
      {showHist && (
        <table style={{ marginTop: 6 }}>
          <thead><tr><th>Version</th><th>Guardrails ID</th><th>Changed</th></tr></thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.version}>
                <td>v{h.version}{h.active && <span className="pill ok" style={{ marginLeft: 6 }}>active</span>}</td>
                <td className="mono">{h.sha256?.slice(0, 12)}</td>
                <td className="dimtxt">{h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// "Connect your agent": a copy-paste LiveKit OTLP snippet (endpoint + token prefilled) plus a
// live "waiting → received" probe. LiveKit is the only shipped framework; BYO-OTLP comes later.
function ConnectPanel(
  { agent, token, onMint }: { agent: Agent; token: string | null; onMint: () => void },
) {
  const [count, setCount] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  // Poll this agent's call count until the first span lands, then stop.
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const calls = await listCalls(200, agent.id);
        if (stop) return;
        setCount(calls.length);
        if (calls.length > 0) return; // received — stop polling
      } catch { /* keep waiting */ }
      if (!stop) timer.current = window.setTimeout(tick, 4000);
    };
    setCount(null);
    tick();
    return () => { stop = true; if (timer.current) window.clearTimeout(timer.current); };
  }, [agent.id]);

  const endpoint = window.location.origin;
  const bearer = token ?? "vo_<mint a token below>";
  const snippet =
    `OTEL_EXPORTER_OTLP_ENDPOINT=${endpoint}\n` +
    `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer ${bearer}`;

  return (
    <div className="panel-card connect">
      <h3>Connect your agent · <span className="fw-tag">LiveKit</span></h3>
      <p className="sub">Point your LiveKit Agents worker's OTLP exporter here. Set these on the
        agent process, then run a call — spans arrive under this agent automatically.</p>
      {!token && (
        <div className="connect-hint">
          <span>Mint an ingest token to fill in the <code>Authorization</code> header.</span>
          <button className="btn-primary" onClick={onMint}>Mint token</button>
        </div>
      )}
      <div className="snippet">
        <button className="copy link" disabled={!token}
          onClick={() => navigator.clipboard?.writeText(snippet)}>Copy</button>
        <pre>{snippet}</pre>
      </div>
      <div className={`conn-status ${count && count > 0 ? "ok" : "wait"}`}>
        {count === null ? "Checking…"
          : count > 0
            ? `✅ Receiving — ${count} call${count === 1 ? "" : "s"} ingested`
            : "Waiting for first span…"}
      </div>
    </div>
  );
}

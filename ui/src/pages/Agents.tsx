import {
  Button, Checkbox, InputField, Modal, ModalBody, ModalFooter, ModalHeader, ModalTitle,
  Textarea,
} from "@actioneer/ads";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAgent,
  deleteAgent,
  deleteCallParams,
  getAgentGuardrails,
  getAgentScript,
  getCallParams,
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
  setParamsRequired,
  getUploadFormat,
  uploadCallParams,
  uploadCalls,
  getJourney,
  setJourney,
  regenerateJourney,
  type JourneyDoc,
  type UploadFormat,
  type UploadMode,
  type UploadOptions,
  type Agent,
  type AgentGuardrails,
  type AgentScript,
  type CallParamsView,
  type IngestTokenRow,
  type MintedToken,
  type RsiRun,
  approveScriptRsi,
  listScriptRsi,
  startScriptRsi,
} from "../api";
import { useAuth } from "../auth";
import { useBackfill } from "../BackfillProvider";

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

  async function add(name: string, script?: string, guardrails?: string, curate = false) {
    setError(null);
    try {
      const a = await createAgent(name.trim(), undefined, script, guardrails, curate);
      setCreating(false);
      load();
      setSel(a.id);
    } catch (e) { setError((e as Error).message); }
  }

  async function rename(a: Agent) {
    const name = prompt("Rename project", a.name)?.trim();
    if (name && name !== a.name) { await renameAgent(a.id, name); load(); }
  }

  async function remove(a: Agent) {
    if (!confirm(`Delete project "${a.name}"? Its calls stay, but it disappears from Pulse.`)) return;
    await deleteAgent(a.id);
    load();
  }

  const selected = agents.find((a) => a.id === sel) ?? null;

  return (
    <div className="settings">
      <div className="settings-hd">
        <h1>Projects</h1>
        <div className="sub">A project holds one voice agent's calls. Upload a ZIP of recordings to
          analyse them.</div>
      </div>
      {error && <div className="auth-error">{error}</div>}
      <div className="settings-cols">
        <div className="col">
          <div className="add-row">
            <Button onClick={() => setCreating(true)}>+ New project</Button>
          </div>
          <table className="project-list">
            <tbody>
              {agents.map((a) => (
                <tr key={a.id} className={a.id === sel ? "on" : undefined}
                  onClick={() => setSel(a.id)}>
                  <td>
                    <div className="strong">{a.name}</div>
                    <div className="mono dimtxt">{a.slug}</div>
                  </td>
                  <td className="r">
                    <Button variant="link" onClick={(e) => { e.stopPropagation(); rename(a); }}>
                      Rename</Button>
                    <Button variant="link" onClick={(e) => { e.stopPropagation(); remove(a); }}>
                      Delete</Button>
                  </td>
                </tr>
              ))}
              {agents.length === 0 && (
                <tr><td className="dimtxt">No projects yet — create one, then upload calls.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="col">
          {selected
            ? <AgentDetail agent={selected} />
            : <div className="empty">Select a project to upload calls and set its script.</div>}
        </div>
      </div>
      {creating && <NewAgentModal onClose={() => setCreating(false)} onCreate={add} />}
    </div>
  );
}

function NewAgentModal(
  { onClose, onCreate }:
  { onClose: () => void;
    onCreate: (name: string, script?: string, guardrails?: string, curate?: boolean) => void },
) {
  const [name, setName] = useState("");
  const [curate, setCurate] = useState(false);
  const [script, setScript] = useState("");
  const [guardrails, setGuardrails] = useState("");

  function submit() {
    if (!name.trim()) return;
    onCreate(name, script.trim() || undefined, guardrails.trim() || undefined, curate);
  }

  return (
    <Modal open onOpenChange={(o) => !o && onClose()} size="lg">
      <ModalHeader><ModalTitle>New project</ModalTitle></ModalHeader>
      <ModalBody>
        <p className="sub">A project holds one voice agent's calls. After creating it, upload a ZIP
          of call recordings to start the analysis.</p>
        <div className="field">
          <InputField label="Name" id="agent-name" autoFocus value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Sales Bot" />
        </div>
        <div className="field">
          <label htmlFor="agent-script">Script <span className="dimtxt">— the prompt this agent
            follows (optional; versioned & hashed)</span></label>
          <Textarea id="agent-script" className="script-area" value={script}
            onChange={(e) => setScript(e.target.value)} rows={4}
            placeholder="e.g. You are a scheduling assistant. Confirm the appointment, then…" />
        </div>

        <div className="field">
          <label htmlFor="agent-guardrails">Guardrails <span className="dimtxt">— rules the agent
            must obey, one per line (optional; versioned & hashed)</span></label>
          <Textarea id="agent-guardrails" className="script-area" value={guardrails}
            onChange={(e) => setGuardrails(e.target.value)} rows={4}
            placeholder={"e.g.\nStay on script; don't be steered off purpose.\nAlways verify the caller before any DB/tool lookup."} />
        </div>

        <label className="toggle-row">
          <Checkbox checked={curate} onChange={(e) => setCurate(e.target.checked)} />
          Create training data — rewrite the agent's failed turns into corrected lines (SFT / DPO export;
          one extra LLM call per call with failures)
        </label>

      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button disabled={!name.trim()} onClick={submit}>Create project</Button>
      </ModalFooter>
    </Modal>
  );
}

// Per-call parameters: upload/paste a CSV of the values a parameterized prompt is rendered with,
// keyed by call id. When "requires call parameters" is on, LLM analysis waits until a call's params
// are present. Reconciliation (re-judging matched calls) happens server-side on upload.
function CallParamsPanel({ agent }: { agent: Agent }) {
  const [view, setView] = useState<CallParamsView | null>(null);
  const [csv, setCsv] = useState("");
  const [keyColumn, setKeyColumn] = useState("call_id");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    getCallParams(agent.id).then(setView).catch(() => setView(null));
  }, [agent.id]);
  useEffect(() => { load(); }, [load]);

  async function toggle(v: boolean) {
    await setParamsRequired(agent.id, v);
    load();
  }

  function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!label) setLabel(f.name);
    f.text().then(setCsv);  // read file → text in the browser; sent as {csv} (no multipart)
  }

  async function upload() {
    if (!csv.trim()) return;
    setBusy(true);
    setMsg(null);
    try {
      const r = await uploadCallParams(agent.id, csv, keyColumn.trim() || "call_id", label.trim() || undefined);
      setMsg(`${r.row_count} rows · ${r.matched} matched to existing calls (re-analysing those).`);
      setCsv(""); setLabel("");
      load();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(uploadId: string) {
    if (!confirm("Delete this parameter set? Calls relying on it lose their params.")) return;
    await deleteCallParams(agent.id, uploadId);
    load();
  }

  return (
    <div className="panel-card">
      <h3>Call parameters · {agent.name}</h3>
      <p className="dimtxt">
        For agents whose system prompt is a template filled per call (e.g. <code>$(CustomerName)</code>),
        upload the per-call values so the LLM analysis judges against the real values. Keyed by the
        call id your exporter emits.
      </p>
      <label className="toggle-row">
        <Checkbox checked={!!view?.params_required}
          onChange={(e) => toggle(e.target.checked)} />
        Requires call parameters (gate LLM analysis until params are uploaded)
      </label>

      <div className="params-upload">
        <div className="row">
          <InputField className="params-key" value={keyColumn}
            onChange={(e) => setKeyColumn(e.target.value)}
            placeholder="call id column" title="CSV column holding the call id" />
          <InputField value={label} onChange={(e) => setLabel(e.target.value)}
            placeholder="label (optional)" />
          <label className="file-btn">
            <input type="file" accept=".csv,text/csv" onChange={pickFile} hidden />
            Choose CSV…
          </label>
        </div>
        <Textarea className="params-csv" rows={5} value={csv} onChange={(e) => setCsv(e.target.value)}
          placeholder={"Paste CSV here (or choose a file above)…\ncall_id,CustomerName,EmiAmount\nvo_abc,Suyog,21226"} />
        <div className="row">
          <Button disabled={busy || !csv.trim()} onClick={upload}>
            {busy ? "Uploading…" : "Upload parameters"}
          </Button>
          {msg && <span className="dimtxt">{msg}</span>}
        </div>
      </div>

      {view && (
        <div className="params-stats dimtxt">
          {view.total_params.toLocaleString()} params stored · {view.awaiting.toLocaleString()} calls
          awaiting parameters
        </div>
      )}
      {view && view.uploads.length > 0 && (
        <table className="params-table">
          <thead><tr><th>Label</th><th>Key</th><th>Rows</th><th>Matched</th><th>Uploaded</th><th /></tr></thead>
          <tbody>
            {view.uploads.map((u) => (
              <tr key={u.id}>
                <td>{u.label || "—"}</td>
                <td className="mono">{u.key_column}</td>
                <td>{u.row_count.toLocaleString()}</td>
                <td>{u.matched_count.toLocaleString()}</td>
                <td>{new Date(u.created_at).toLocaleDateString()}</td>
                <td><button className="link-danger" onClick={() => remove(u.id)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}


function AgentDetail({ agent }: { agent: Agent }) {
  const [tokens, setTokens] = useState<IngestTokenRow[]>([]);
  // The last plaintext token from this session's mint/rotate — the only time we ever see it.
  // Shared so the Connect snippet can show a real Bearer header, then management can revoke it.
  const [minted, setMinted] = useState<MintedToken | null>(null);
  const [name, setName] = useState("");
  const [scriptRev, setScriptRev] = useState(0);  // bumps on script save -> upload schemas refresh

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
      <UploadPanel agent={agent} scriptRev={scriptRev} />
      <ScriptPanel agent={agent} rev={scriptRev} onSaved={() => setScriptRev((n) => n + 1)} />
      <JourneyPanel agent={agent} scriptRev={scriptRev} />
      <ImprovePanel agent={agent} onApproved={() => setScriptRev((n) => n + 1)} />
      <GuardrailsPanel agent={agent} />
      <CallParamsPanel agent={agent} />
      <details className="panel-card advanced">
        <summary>Live ingest (OTLP) — advanced</summary>
      <ConnectPanel agent={agent} token={minted?.token ?? null} onMint={mint} />
      <div className="panel-card">
        <h3>Ingest tokens · {agent.name}</h3>
        {minted && (
          <div className="minted">
            <div className="minted-hd">Copy this token now — it is shown only once.</div>
            <code className="mono">{minted.token}</code>
            <Button variant="link" onClick={() => navigator.clipboard?.writeText(minted.token)}>
              Copy</Button>
          </div>
        )}
        <div className="add-row">
          <input value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && mint()} placeholder="Label (e.g. prod)…" />
          <Button onClick={mint}>Mint token</Button>
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
                    <Button variant="link" onClick={() => rotate(t)}>Rotate</Button>
                    <Button variant="link" onClick={() => revoke(t)}>Revoke</Button>
                  </>}
                </td>
              </tr>
            ))}
            {tokens.length === 0 && <tr><td colSpan={4} className="dimtxt">No tokens yet.</td></tr>}
          </tbody>
        </table>
      </div>
      </details>
    </>
  );
}

// Start analysis from files, exactly one of
//   1. a CSV of call parameters + the audio ZIP -> Pulse transcribes (Sarvam), then analyses;
//   2. a pulse.calls.v1 JSON (transcripts + params) -> no transcription; the audio ZIP is optional
//      (playback only).
// The format box is a copy-paste spec (rules + schema + example) using this project's own
// placeholder names, so it can be handed straight to a coding agent to generate the file.
function UploadPanel({ agent, scriptRev }: { agent: Agent; scriptRev: number }) {
  const { follow, job } = useBackfill();
  const [mode, setMode] = useState<UploadMode>("csv");
  const [zip, setZip] = useState<File | null>(null);
  const [side, setSide] = useState<File | null>(null);
  const [channel, setChannel] = useState<UploadOptions["agentChannel"]>("auto");
  const [language, setLanguage] = useState("hi-IN");
  const [sent, setSent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [spec, setSpec] = useState<UploadFormat | null>(null);
  const [copied, setCopied] = useState(false);
  const zipRef = useRef<HTMLInputElement>(null);
  const sideRef = useRef<HTMLInputElement>(null);

  // Re-read whenever the script changes: the schemas are its placeholders.
  useEffect(() => { getUploadFormat(agent.id).then(setSpec).catch(() => setSpec(null)); },
    [agent.id, scriptRev]);
  // Uploading needs a script with {{placeholders}} — the per-call parameters come from them.
  const ready = !!spec?.has_script && spec.params.length > 0;
  // …and its script journey processed, so the analysis starts the moment calls arrive.
  const { processing } = useScriptProcessing(agent.id, scriptRev);

  const mine = job && job.agent_id === agent.id ? job : null;
  const busy = sent !== null || (!!mine && !["done", "failed", "cancelled"].includes(mine.status));

  function switchMode(m: UploadMode) {
    setMode(m); setSide(null); setError(null);
    if (sideRef.current) sideRef.current.value = "";
  }

  async function start() {
    if (!side || (mode === "csv" && !zip)) return;
    setError(null);
    setSent(0);
    try {
      const j = await uploadCalls(agent.id, zip, { mode, file: side },
        { agentChannel: channel, language }, setSent);
      follow(j);
      setZip(null); setSide(null);
      if (zipRef.current) zipRef.current.value = "";
      if (sideRef.current) sideRef.current.value = "";
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSent(null);
    }
  }

  // Just the schemas: the CSV header (one column per script placeholder) with sample rows, and
  // the JSON Schema of pulse.calls.v1.
  const specText = !spec ? "Loading…" : !ready ? "" : mode === "csv"
    ? spec.csv.example
    : JSON.stringify(spec.json.schema, null, 2);

  function copy() {
    navigator.clipboard?.writeText(specText).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1500);
    });
  }

  return (
    <div className="panel-card">
      <h3>Analyse calls · {agent.name}</h3>
      {spec && !ready && (
        <div className="upload-gate">
          {!spec.has_script
            ? <>Add this project's <b>script</b> first (Script panel below). Write per-call values as
              <code> {"{{placeholders}}"}</code>, e.g. <code>{"{{customer_name}}"}</code> — they become
              the columns of the parameters file.</>
            : <>The script has no <code>{"{{placeholders}}"}</code>. Mark the per-call values in it
              (e.g. <code>{"{{customer_name}}"}</code>) — every upload needs them.</>}
        </div>
      )}
      <fieldset className="upload-body" disabled={!ready}>
      <div className="mode-switch">
        <button type="button" className={mode === "csv" ? "on" : ""} onClick={() => switchMode("csv")}>
          <b>Audio + parameters</b><span>ZIP + CSV · Pulse transcribes</span></button>
        <button type="button" className={mode === "json" ? "on" : ""} onClick={() => switchMode("json")}>
          <b>Transcripts</b><span>JSON (+ optional audio ZIP) · no transcription</span></button>
      </div>
      {ready && (
        <p className="dimtxt">Per-call parameters from the script: {spec.params.map((p) => (
          <code key={p} className="param-chip">{p}</code>))}</p>
      )}
      <div className="params-upload">
        <div className="row">
          <label className="file-btn">
            <input ref={zipRef} type="file" accept=".zip,application/zip" hidden
              onChange={(e) => setZip(e.target.files?.[0] ?? null)} />
            {zip ? `ZIP: ${zip.name}` : mode === "csv" ? "Choose audio ZIP…" : "Choose audio ZIP (optional)…"}
          </label>
          <label className="file-btn">
            <input ref={sideRef} type="file" hidden
              accept={mode === "csv" ? ".csv,text/csv" : ".json,application/json"}
              onChange={(e) => setSide(e.target.files?.[0] ?? null)} />
            {side ? `${mode.toUpperCase()}: ${side.name}`
              : mode === "csv" ? "Choose parameters CSV…" : "Choose transcripts JSON…"}
          </label>
        </div>
        {mode === "csv" && (
          <div className="row">
            <label className="dimtxt">Agent voice is on{" "}
              <select value={channel}
                onChange={(e) => setChannel(e.target.value as UploadOptions["agentChannel"])}>
                <option value="auto">auto-detect</option>
                <option value="left">left channel</option>
                <option value="right">right channel</option>
              </select>
            </label>
            <label className="dimtxt">Language{" "}
              <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                <option value="hi-IN">Hindi / Hinglish</option>
                <option value="en-IN">English (India)</option>
                <option value="unknown">Auto-detect</option>
                <option value="bn-IN">Bengali</option>
                <option value="gu-IN">Gujarati</option>
                <option value="kn-IN">Kannada</option>
                <option value="ml-IN">Malayalam</option>
                <option value="mr-IN">Marathi</option>
                <option value="od-IN">Odia</option>
                <option value="pa-IN">Punjabi</option>
                <option value="ta-IN">Tamil</option>
                <option value="te-IN">Telugu</option>
              </select>
            </label>
          </div>
        )}
        <div className="row">
          <Button disabled={!ready || processing || !side || (mode === "csv" && !zip) || busy} onClick={start}>
            {sent !== null ? `Uploading… ${Math.round(sent * 100)}%` : "Start analysis"}
          </Button>
          {processing && <span className="dimtxt"><span className="spinner" /> Processing the script — analysis can start once
            it's ready (about 2 minutes; you can close this tab).</span>}
          {mine && (
            <span className="dimtxt">
              {mine.status === "done" ? `Done — ${mine.completed} analysed, ${mine.failed} failed`
                : mine.status === "failed" ? `Failed: ${mine.error ?? "unknown error"}`
                : `${mine.phase ?? mine.status}… ${mine.completed + mine.failed}/${mine.total || "?"}`}
            </span>
          )}
        </div>
        {error && <div className="auth-error upload-errors">{error}</div>}
      </div>
      <div className="format-box">
        <div className="format-hd">
          <span>{mode === "csv" ? "CSV schema" : `JSON schema · ${spec?.format ?? ""}`}</span>
          <Button variant="link" onClick={copy} disabled={!ready}>{copied ? "Copied" : "Copy"}</Button>
        </div>
        {ready && <pre className="mono json-example">{specText}</pre>}
      </div>
      </fieldset>
    </div>
  );
}

// The journey: the active script version, structured (stages in order, what the customer can do at each,
// anytime branches incl. Pulse's standard rules, guardrails). Extracted in the background after a script
// save; every call on that version is judged against it. Editable as JSON.
function JourneyPanel({ agent, scriptRev }: { agent: Agent; scriptRev: number }) {
  const [doc, setDoc] = useState<JourneyDoc | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(() => {
    getJourney(agent.id).then(setDoc).catch(() => setDoc(null));
  }, [agent.id]);
  useEffect(() => { load(); setEditing(false); setMsg(null); }, [load, scriptRev]);
  // Poll while extraction is in flight.
  useEffect(() => {
    if (!doc || !["pending", "extracting"].includes(doc.status)) return;
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [doc, load]);

  async function regenerate() {
    setDoc(await regenerateJourney(agent.id));
  }
  async function save() {
    setMsg(null);
    try {
      setDoc(await setJourney(agent.id, JSON.parse(text)));
      setEditing(false);
    } catch (e) {
      setMsg((e as Error).message);
    }
  }

  const j = doc?.journey;
  return (
    <div className="panel-card">
      <h3>Script journey · {agent.name}
        {doc?.version != null && <span className="pill" style={{ marginLeft: 8 }}>script v{doc.version}</span>}
        {doc && <span className={`pill ${doc.status === "ready" ? "good" : doc.status === "failed" ? "bad" : ""}`}
          style={{ marginLeft: 6 }}>{doc.status === "extracting" || doc.status === "pending"
            ? "extracting…" : doc.status.replace("_", " ")}{doc.edited ? " · edited" : ""}</span>}
      </h3>
      <p className="dimtxt">The script, structured: stages in order, what the customer can do at each and how the
        agent should respond, and the rules for the whole call. Every call on this script version is judged
        against it.</p>
      {doc?.status === "no_script" && <p className="dimtxt">Add the project's script first.</p>}
      {doc?.status === "failed" && <div className="auth-error">Extraction failed: {doc.error}</div>}
      {j && !editing && (
        <div className="journey-view">
          <div className="jv-obj"><b>Objective</b> · {j.objective}</div>
          {j.params.length > 0 && <div className="dimtxt">Parameters: {j.params.map((p) => (
            <code key={p} className="param-chip">{p}</code>))}</div>}
          {j.opening && <div className="jv-bookend"><b>Opening</b> <span className="dimtxt">— {j.opening.agent}</span></div>}
          <ol className="jv-stages">
            {j.funnel.map((s) => (
              <li key={s.stage}>
                <div><b>{s.stage}</b> <span className="dimtxt">— {s.agent}</span></div>
                <div className="dimtxt">done when: {s.done_when}</div>
                {s.side.length > 0 && (
                  <ul className="jv-side">
                    {s.side.map((b) => <li key={b.if}>if <i>{b.if}</i> → {b.then} <span className="dimtxt">→ {b.goes_to}</span></li>)}
                  </ul>
                )}
              </li>
            ))}
          </ol>
          {j.closing && <div className="jv-bookend"><b>Closing</b> <span className="dimtxt">— {j.closing.agent}</span></div>}
          {j.anytime.length > 0 && (
            <>
              <div className="jr-hd">Any time</div>
              <ul className="jv-side">
                {j.anytime.map((b) => (
                  <li key={b.if}>if <i>{b.if}</i> → {b.then} <span className="dimtxt">→ {b.goes_to}</span>
                    {b.standard && <span className="pill" style={{ marginLeft: 6 }}>Pulse rule</span>}
                    {b.standard && b.in_script === false && <span className="cause-chip script_gap">not in script</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {j.guardrails.length > 0 && (
            <>
              <div className="jr-hd">Guardrails</div>
              <ul className="jv-side">{j.guardrails.map((g) => <li key={g.rule}>{g.rule}</li>)}</ul>
            </>
          )}
        </div>
      )}
      {editing && (
        <Textarea className="script-area" rows={16} value={text} onChange={(e) => setText(e.target.value)} />
      )}
      <div className="row" style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
        {j && !editing && <Button variant="ghost" onClick={() => { setText(JSON.stringify(j, null, 2)); setEditing(true); }}>Edit</Button>}
        {editing && <><Button onClick={save}>Save script journey</Button>
          <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button></>}
        {doc && doc.status !== "no_script" && !editing && <Button variant="link" onClick={regenerate}>Regenerate from script</Button>}
        {msg && <span className="auth-error">{msg}</span>}
      </div>
    </div>
  );
}

// The agent's script — the prompt it's meant to follow. Versioned + hash-addressed; each call
// pins the version it ran under. Owner/admin edits (viewers get 403 from the API).
function ScriptPanel({ agent, onSaved, rev }: { agent: Agent; onSaved?: () => void; rev: number }) {
  const { processing } = useScriptProcessing(agent.id, rev);
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
    onSaved?.();
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
      <Textarea className="script-area" rows={6} value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); setSaved(false); }}
        placeholder="No script set. Add the prompt this agent is meant to follow…" />
      <div className="add-row" style={{ marginTop: 8 }}>
        <Button disabled={!dirty || !text.trim() || processing} onClick={save}>
          {processing ? "Processing script…" : script ? "Save new version" : "Save script"}</Button>
        {processing && <span className="spinner" aria-label="processing" />}
        {saved && !processing && <span className="dimtxt" style={{ alignSelf: "center" }}>saved ✓</span>}
        {history.length > 0 && (
          <Button variant="link" style={{ marginLeft: "auto" }}
            onClick={() => setShowHist((v) => !v)}>
            {showHist ? "Hide" : `History (${history.length})`}</Button>
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
      <Textarea className="script-area" rows={6} value={text}
        onChange={(e) => { setText(e.target.value); setDirty(true); setSaved(false); }}
        placeholder={"No guardrails set. One rule per line, e.g.\nStay on script; don't be steered off purpose.\nAlways verify the caller before any DB/tool lookup."} />
      <div className="add-row" style={{ marginTop: 8 }}>
        <Button disabled={!dirty || !text.trim()} onClick={save}>
          {gr ? "Save new version" : "Save guardrails"}</Button>
        {saved && <span className="dimtxt" style={{ alignSelf: "center" }}>saved ✓</span>}
        {history.length > 0 && (
          <Button variant="link" style={{ marginLeft: "auto" }}
            onClick={() => setShowHist((v) => !v)}>
            {showHist ? "Hide" : `History (${history.length})`}</Button>
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
          <Button onClick={onMint}>Mint token</Button>
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


// Script improvement: from the Analysis (what the script misses + what the agent didn't follow), build
// improved scripts — additions only, A (revise what wasn't followed) and B (restructure the flow) — each
// with its change list and rendered text; approve one to make it the next script version.
const VARIANTS: [string, string][] = [["additions", "Additions only"], ["A", "A — revise"], ["B", "B — restructure"]];

function ImprovePanel({ agent, onApproved }: { agent: Agent; onApproved: () => void }) {
  const [run, setRun] = useState<RsiRun | null>(null);
  const [tab, setTab] = useState("A");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    listScriptRsi(agent.id).then((r) => setRun(r.items[0] ?? null)).catch(() => setRun(null));
  }, [agent.id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (run?.status !== "pending" && run?.status !== "running") return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [run?.status, load]);

  async function start() {
    setBusy(true); setError(null);
    try { setRun(await startScriptRsi(agent.id)); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  async function approve() {
    if (!run) return;
    setBusy(true); setError(null);
    try { await approveScriptRsi(agent.id, run.id, tab); load(); onApproved(); } catch (e) { setError((e as Error).message); }
    setBusy(false);
  }
  const v = run?.result?.variants?.[tab];
  const working = run?.status === "pending" || run?.status === "running";
  return (
    <div className="panel-card">
      <h3>Improve script · {agent.name}
        {run && <span className="pill" style={{ marginLeft: 8 }}>{working ? "working…" : run.status}</span>}
      </h3>
      <p className="dimtxt">Builds improved versions of the script from the Analysis: what the script doesn't
        cover gets added (merged into general rules where they share a principle), and what the agent didn't
        follow gets revised (A) or the flow restructured (B). Nothing changes until you approve one.</p>
      {error && <div className="auth-error">{error}</div>}
      {run?.status === "failed" && <div className="auth-error">{run.error}</div>}
      <Button disabled={busy || working} onClick={start}>{run ? "Run again" : "Improve script"}</Button>
      {run?.status === "ready" && run.result && (
        <>
          <div className="rsi-tabs">
            {VARIANTS.map(([k, l]) => (
              <button key={k} className={k === tab ? "on" : ""} onClick={() => setTab(k)}>
                {l} <span className="dimtxt">· {run.result!.variants[k]?.chars.toLocaleString()} chars</span>
              </button>
            ))}
          </div>
          {v && (
            <>
              <div className="jr-hd">Changes ({v.changes.length})</div>
              <ul className="rsi-changes">
                {v.changes.map((c, i) => (
                  <li key={i}><b>{c.change}</b> {c.section} · {c.id}{c.at ? <span className="dimtxt"> · {c.at}</span> : null}
                    {c.reason && <div className="dimtxt">{c.reason}</div>}</li>
                ))}
              </ul>
              {v.ops && v.ops.some((o) => !o.applied) && (
                <div className="dimtxt">Rejected restructure steps: {v.ops.filter((o) => !o.applied)
                  .map((o) => `${o.op} (${o.rejected})`).join("; ")}</div>
              )}
              <details><summary>Script text</summary><pre className="rsi-text">{v.text}</pre></details>
              <Button disabled={busy || run.approved_variant != null} onClick={approve}>
                {run.approved_variant ? `Approved: ${run.approved_variant}` : "Approve as the next version"}</Button>
            </>
          )}
          {run.result.training.length > 0 && (
            <>
              <div className="jr-hd">Fix with training data (the script is clear; the agent didn't follow it)</div>
              <ul className="rsi-changes">
                {run.result.training.map((t, i) => <li key={i}>{t.item} <span className="dimtxt">· {t.kind} · {t.calls} calls</span></li>)}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}


// Whether the project's active script is still being processed into its script journey. Server state,
// polled while it runs — closing the tab loses nothing.
function useScriptProcessing(agentId: string, rev: number): { processing: boolean; failed: boolean } {
  const [status, setStatus] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = () => getJourney(agentId).then((d) => {
      if (!alive) return;
      setStatus(d.status);
      if (d.status === "pending" || d.status === "extracting") timer = setTimeout(poll, 3000);
    }).catch(() => undefined);
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [agentId, rev]);
  return { processing: status === "pending" || status === "extracting", failed: status === "failed" };
}

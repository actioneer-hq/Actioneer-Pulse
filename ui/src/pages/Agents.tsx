import { useCallback, useEffect, useRef, useState } from "react";
import {
  createAgent,
  deleteAgent,
  listAgents,
  listCalls,
  listTokens,
  mintToken,
  renameAgent,
  revokeToken,
  rotateToken,
  type Agent,
  type IngestTokenRow,
  type MintedToken,
} from "../api";
import { useAuth } from "../auth";

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

  async function add(name: string) {
    setError(null);
    try {
      const a = await createAgent(name.trim());
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
  { onClose, onCreate }: { onClose: () => void; onCreate: (name: string) => void },
) {
  const [name, setName] = useState("");
  const [framework, setFramework] = useState("livekit");

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>New agent</h3>
        <p className="sub">An agent is a project / OTLP routing target. Pick the framework your
          voice agent runs on, then connect it with an ingest token.</p>
        <div className="field">
          <label htmlFor="agent-name">Name</label>
          <input id="agent-name" autoFocus value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && onCreate(name)}
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
        <div className="modal-foot">
          <button className="link" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!name.trim()}
            onClick={() => onCreate(name)}>Create agent</button>
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

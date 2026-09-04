import { useCallback, useEffect, useState } from "react";
import {
  createAgent,
  deleteAgent,
  listAgents,
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

export default function Agents() {
  const { activeOrg } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listAgents().then((a) => {
      setAgents(a);
      setSel((cur) => (a.some((x) => x.id === cur) ? cur : a[0]?.id ?? null));
    }).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => { load(); }, [load, activeOrg]);

  async function add() {
    if (!newName.trim()) return;
    setError(null);
    try {
      const a = await createAgent(newName.trim());
      setNewName("");
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
            <input value={newName} onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && add()} placeholder="New agent name…" />
            <button className="btn-primary" onClick={add}>Add</button>
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
            ? <TokenPanel agent={selected} />
            : <div className="empty">Select an agent to manage its ingest tokens.</div>}
        </div>
      </div>
    </div>
  );
}

function TokenPanel({ agent }: { agent: Agent }) {
  const [tokens, setTokens] = useState<IngestTokenRow[]>([]);
  const [minted, setMinted] = useState<MintedToken | null>(null);
  const [name, setName] = useState("");

  const load = useCallback(() => { listTokens(agent.id).then(setTokens).catch(() => setTokens([])); },
    [agent.id]);
  useEffect(() => { load(); setMinted(null); }, [load]);

  async function mint() {
    const m = await mintToken(agent.id, name.trim() || undefined);
    setMinted(m);
    setName("");
    load();
  }
  async function rotate(t: IngestTokenRow) {
    const m = await rotateToken(agent.id, t.id);
    setMinted(m);
    load();
  }
  async function revoke(t: IngestTokenRow) {
    if (!confirm("Revoke this token? Producers using it stop working immediately.")) return;
    await revokeToken(agent.id, t.id);
    load();
  }

  return (
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
  );
}

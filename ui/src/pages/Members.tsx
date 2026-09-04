import { useCallback, useEffect, useState } from "react";
import {
  addMember,
  listAgents,
  listMembers,
  removeMember,
  setAgentAccess,
  setRole,
  type Agent,
  type Member,
  type Role,
} from "../api";
import { useAuth } from "../auth";

const ROLES: Role[] = ["owner", "admin", "member", "viewer"];

export default function Members() {
  const { activeOrg } = useAuth();
  const [members, setMembers] = useState<Member[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [email, setEmail] = useState("");
  const [role, setNewRole] = useState<Role>("member");
  const [invite, setInvite] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [grantFor, setGrantFor] = useState<Member | null>(null);

  const load = useCallback(() => {
    if (!activeOrg) return;
    listMembers(activeOrg).then(setMembers).catch((e: Error) => setError(e.message));
    listAgents().then(setAgents).catch(() => setAgents([]));
  }, [activeOrg]);
  useEffect(() => { load(); }, [load]);

  async function inviteMember() {
    if (!activeOrg || !email.trim()) return;
    setError(null);
    try {
      const r = await addMember(activeOrg, email.trim(), role);
      setEmail("");
      // A brand-new person comes back with an invite token → build the accept link.
      setInvite(r.invite_token
        ? `${location.origin}/accept-invite?token=${r.invite_token}`
        : null);
      load();
    } catch (e) { setError((e as Error).message); }
  }

  async function changeRole(m: Member, next: Role) {
    if (!activeOrg) return;
    await setRole(activeOrg, m.membership_id, next);
    load();
  }
  async function kick(m: Member) {
    if (!activeOrg || !confirm(`Remove ${m.email ?? m.user_id} from this org?`)) return;
    await removeMember(activeOrg, m.membership_id);
    load();
  }

  return (
    <div className="settings">
      <div className="settings-hd">
        <h1>Members</h1>
        <div className="sub">Coarse role plus granular per-agent grants. A member/viewer with no
          grants sees all agents; adding a grant restricts them to it.</div>
      </div>
      {error && <div className="auth-error">{error}</div>}
      <div className="add-row wide">
        <input value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="person@company.com" />
        <select value={role} onChange={(e) => setNewRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button className="btn-primary" onClick={inviteMember}>Invite</button>
      </div>
      {invite && (
        <div className="minted">
          <div className="minted-hd">Send this invite link — it sets their password.</div>
          <code className="mono">{invite}</code>
          <button className="link" onClick={() => navigator.clipboard?.writeText(invite)}>Copy</button>
        </div>
      )}
      <table>
        <thead>
          <tr><th>Email</th><th>Role</th><th>Agent access</th><th></th></tr>
        </thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.membership_id}>
              <td>{m.email ?? <span className="dimtxt">{m.user_id}</span>}</td>
              <td>
                <select value={m.role} onChange={(e) => changeRole(m, e.target.value as Role)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </td>
              <td>
                {m.role === "owner" || m.role === "admin"
                  ? <span className="dimtxt">all (admin)</span>
                  : <button className="link" onClick={() => setGrantFor(m)}>Edit grants</button>}
              </td>
              <td className="r">
                <button className="link bad" onClick={() => kick(m)}>Remove</button>
              </td>
            </tr>
          ))}
          {members.length === 0 && <tr><td colSpan={4} className="dimtxt">No members.</td></tr>}
        </tbody>
      </table>
      {grantFor && activeOrg && (
        <GrantEditor orgId={activeOrg} member={grantFor} agents={agents}
          onClose={() => setGrantFor(null)} onSaved={() => { setGrantFor(null); load(); }} />
      )}
    </div>
  );
}

function GrantEditor(
  { orgId, member, agents, onClose, onSaved }:
  { orgId: string; member: Member; agents: Agent[]; onClose: () => void; onSaved: () => void },
) {
  // The API replaces the whole grant set; we can't read the current set back, so this
  // starts empty and the admin picks the agents to restrict to (empty = coarse default).
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) =>
    setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  async function save() {
    setBusy(true);
    await setAgentAccess(orgId, member.membership_id, [...picked]);
    setBusy(false);
    onSaved();
  }

  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Agent access · {member.email ?? member.user_id}</h3>
        <p className="sub">Select the agents this member may see. Leave all unchecked to give
          access to every agent in the org.</p>
        <div className="grant-list">
          {agents.map((a) => (
            <label key={a.id} className="grant-item">
              <input type="checkbox" checked={picked.has(a.id)} onChange={() => toggle(a.id)} />
              <span>{a.name}</span>
            </label>
          ))}
          {agents.length === 0 && <div className="dimtxt">No agents in this org yet.</div>}
        </div>
        <div className="modal-foot">
          <button className="link" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={save} disabled={busy}>Save grants</button>
        </div>
      </div>
    </div>
  );
}

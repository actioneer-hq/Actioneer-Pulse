import {
  Alert, Button, Checkbox, InputField, Modal, ModalBody, ModalFooter, ModalHeader, ModalTitle,
  Select, Table, TableBody, TableCell, TableColumn, TableHeader, TableRow,
} from "@actioneer/ads";
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
const ROLE_ITEMS = ROLES.map((r) => ({ label: r, value: r }));

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
      {error && <Alert variant="danger">{error}</Alert>}
      <div className="add-row wide">
        <InputField value={email} onChange={(e) => setEmail(e.target.value)}
          placeholder="person@company.com" />
        <Select value={role} onChange={(v) => setNewRole(v as Role)} items={ROLE_ITEMS} />
        <Button onClick={inviteMember}>Invite</Button>
      </div>
      {invite && (
        <div className="minted">
          <div className="minted-hd">Send this invite link — it sets their password.</div>
          <code className="mono">{invite}</code>
          <Button variant="link" size="sm" onClick={() => navigator.clipboard?.writeText(invite)}>Copy</Button>
        </div>
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableColumn>Email</TableColumn><TableColumn>Role</TableColumn>
            <TableColumn>Agent access</TableColumn><TableColumn />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.map((m) => (
            <TableRow key={m.membership_id}>
              <TableCell>{m.email ?? <span className="dimtxt">{m.user_id}</span>}</TableCell>
              <TableCell>
                <Select value={m.role} onChange={(v) => changeRole(m, v as Role)} items={ROLE_ITEMS} size="sm" />
              </TableCell>
              <TableCell>
                {m.role === "owner" || m.role === "admin"
                  ? <span className="dimtxt">all (admin)</span>
                  : <Button variant="link" size="sm" onClick={() => setGrantFor(m)}>Edit grants</Button>}
              </TableCell>
              <TableCell className="r">
                <Button variant="link" size="sm" onClick={() => kick(m)}>Remove</Button>
              </TableCell>
            </TableRow>
          ))}
          {members.length === 0 && (
            <TableRow><TableCell colSpan={4} className="dimtxt">No members.</TableCell></TableRow>
          )}
        </TableBody>
      </Table>
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
    <Modal open onOpenChange={(o) => !o && onClose()}>
      <ModalHeader><ModalTitle>Agent access · {member.email ?? member.user_id}</ModalTitle></ModalHeader>
      <ModalBody>
        <p className="sub">Select the agents this member may see. Leave all unchecked to give
          access to every agent in the org.</p>
        <div className="grant-list">
          {agents.map((a) => (
            <label key={a.id} className="grant-item">
              <Checkbox checked={picked.has(a.id)} onChange={() => toggle(a.id)} />
              <span>{a.name}</span>
            </label>
          ))}
          {agents.length === 0 && <div className="dimtxt">No agents in this org yet.</div>}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button onClick={save} disabled={busy} isLoading={busy}>Save grants</Button>
      </ModalFooter>
    </Modal>
  );
}

import {
  Avatar, Button, Dropdown, DropdownContent, DropdownItem, DropdownLabel, DropdownSeparator,
  DropdownTrigger, EmptyState, Select,
} from "@actioneer/ads";
import { type ReactNode } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { useActiveAgent } from "./ActiveAgentProvider";
import { RequireAdmin, RequireAuth, useAuth, useAuthRedirect } from "./auth";
import Agents from "./pages/Agents";
import Boards from "./pages/Boards";
import Calls from "./pages/Calls";
import Chat from "./pages/Chat";
import Clusters from "./pages/Clusters";
import Login from "./pages/Login";
import Members from "./pages/Members";
import BackfillToast from "./components/BackfillToast";

// The chrome around every signed-in page: brand, primary nav, org selector, user menu.
function Shell() {
  const { user, isAdmin, memberships, activeOrg, setActiveOrg, logout } = useAuth();

  return (
    <>
      <div className="top">
        <div className="brand">
          <img className="logo" src="/actioneer-logo.svg" alt="Actioneer" />
          <span className="brand-sep" />
          <img className="pulse-wordmark" src="/pulse-wordmark.png" alt="Pulse" />
        </div>
        <nav>
          <NavLink to="/calls" className={({ isActive }) => (isActive ? "on" : undefined)}>
            Calls
          </NavLink>
          <NavLink to="/chat" className={({ isActive }) => (isActive ? "on" : undefined)}>
            Chat
          </NavLink>
          <NavLink to="/boards" className={({ isActive }) => (isActive ? "on" : undefined)}>
            Boards
          </NavLink>
          <NavLink to="/clusters" className={({ isActive }) => (isActive ? "on" : undefined)}>
            Clusters
          </NavLink>
          {isAdmin && (
            <>
              <NavLink to="/settings/agents"
                className={({ isActive }) => (isActive ? "on" : undefined)}>
                Agents
              </NavLink>
              <NavLink to="/settings/members"
                className={({ isActive }) => (isActive ? "on" : undefined)}>
                Members
              </NavLink>
            </>
          )}
        </nav>
        <div className="top-right">
          <ProjectSelect />
          {memberships.length > 1 ? (
            <Select value={activeOrg ?? ""} onChange={setActiveOrg} size="sm"
              items={memberships.map((m) => ({ value: m.org_id, label: m.org_name ?? m.org_id }))} />
          ) : (
            <span className="org-name">{memberships[0]?.org_name}</span>
          )}
          <Dropdown>
            <DropdownTrigger>
              <button className="avatar-btn" title={user?.email} aria-label="Account menu">
                <Avatar name={user?.email ?? "?"} size="sm" />
              </button>
            </DropdownTrigger>
            <DropdownContent align="end">
              <DropdownLabel>{user?.email}</DropdownLabel>
              <DropdownSeparator />
              <DropdownItem onClick={() => void logout()}>Sign out</DropdownItem>
              <DropdownItem onClick={() => void logout(true)}>Sign out everywhere</DropdownItem>
            </DropdownContent>
          </Dropdown>
        </div>
      </div>
      <BackfillToast />
      <Outlet />
    </>
  );
}

// The global project (agent) switcher — everything in the main views scopes to it.
function ProjectSelect() {
  const { agents, activeAgent, setActiveAgent } = useActiveAgent();
  if (agents.length === 0) {
    return (
      <NavLink to="/settings/agents" className="project-empty">
        ＋ Create a project
      </NavLink>
    );
  }
  return (
    <Select value={activeAgent ?? ""} onChange={setActiveAgent} size="sm"
      items={agents.map((a) => ({ value: a.id, label: a.name }))} />
  );
}

// Data views require a project. With none, prompt to create one (settings stays reachable).
function RequireAgent({ children }: { children: ReactNode }) {
  const { agents, loading } = useActiveAgent();
  if (loading) return null;
  if (agents.length === 0) {
    return (
      <div className="empty-state">
        <EmptyState
          title="No projects yet"
          description="A project is a voice agent. Create one to see its calls, metrics, and chat."
          action={<NavLink to="/settings/agents"><Button>Create a project</Button></NavLink>}
        />
      </div>
    );
  }
  return <>{children}</>;
}

export default function App() {
  useAuthRedirect();
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/accept-invite" element={<Login />} />
      <Route element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<Navigate to="/calls" replace />} />
        <Route path="/calls" element={<RequireAgent><Calls /></RequireAgent>} />
        <Route path="/chat" element={<RequireAgent><Chat /></RequireAgent>} />
        <Route path="/boards" element={<RequireAgent><Boards /></RequireAgent>} />
        <Route path="/clusters" element={<RequireAgent><Clusters /></RequireAgent>} />
        <Route path="/settings/agents"
          element={<RequireAdmin><Agents /></RequireAdmin>} />
        <Route path="/settings/members"
          element={<RequireAdmin><Members /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/calls" replace />} />
    </Routes>
  );
}

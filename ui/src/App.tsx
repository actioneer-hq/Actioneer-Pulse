import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { RequireAdmin, RequireAuth, useAuth, useAuthRedirect } from "./auth";
import Agents from "./pages/Agents";
import Boards from "./pages/Boards";
import Calls from "./pages/Calls";
import Chat from "./pages/Chat";
import Login from "./pages/Login";
import Members from "./pages/Members";

// The chrome around every signed-in page: brand, primary nav, org selector, user menu.
function Shell() {
  const { user, isAdmin, memberships, activeOrg, setActiveOrg, logout } = useAuth();
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

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
          {memberships.length > 1 ? (
            <select className="org-select" value={activeOrg ?? ""}
              onChange={(e) => setActiveOrg(e.target.value)}>
              {memberships.map((m) => (
                <option key={m.org_id} value={m.org_id}>{m.org_name ?? m.org_id}</option>
              ))}
            </select>
          ) : (
            <span className="org-name">{memberships[0]?.org_name}</span>
          )}
          <div className="usermenu" ref={menuRef}>
            <button className="avatar" onClick={() => setMenu((v) => !v)} title={user?.email}>
              {(user?.email ?? "?").slice(0, 1).toUpperCase()}
            </button>
            {menu && (
              <div className="menu">
                <div className="menu-hd">{user?.email}</div>
                <button onClick={() => void logout()}>Sign out</button>
                <button onClick={() => void logout(true)}>Sign out everywhere</button>
              </div>
            )}
          </div>
        </div>
      </div>
      <Outlet />
    </>
  );
}

export default function App() {
  useAuthRedirect();
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/accept-invite" element={<Login />} />
      <Route element={<RequireAuth><Shell /></RequireAuth>}>
        <Route index element={<Navigate to="/calls" replace />} />
        <Route path="/calls" element={<Calls />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/boards" element={<Boards />} />
        <Route path="/settings/agents"
          element={<RequireAdmin><Agents /></RequireAdmin>} />
        <Route path="/settings/members"
          element={<RequireAdmin><Members /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/calls" replace />} />
    </Routes>
  );
}

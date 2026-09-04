import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import {
  getMe,
  logout as apiLogout,
  logoutEverywhere as apiLogoutAll,
  setApiOrg,
  setUnauthorizedHandler,
  type Me,
  type Membership,
  type Role,
} from "./api";

const ORG_KEY = "voiceobs.activeOrg";
const ADMIN: Role[] = ["owner", "admin"];

type AuthState = {
  ready: boolean; // the initial getMe() has resolved (success or 401)
  user: Me["user"] | null;
  memberships: Membership[];
  activeOrg: string | null;
  role: Role | null;
  isAdmin: boolean;
  setActiveOrg: (orgId: string) => void;
  refresh: () => Promise<void>;
  logout: (everywhere?: boolean) => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState<Me | null>(null);
  const [activeOrg, setActiveOrgState] = useState<string | null>(
    () => localStorage.getItem(ORG_KEY),
  );

  // Keep the api layer's org header in sync before any request goes out.
  useEffect(() => { setApiOrg(activeOrg); }, [activeOrg]);

  const refresh = useCallback(async () => {
    try {
      const next = await getMe();
      setMe(next);
      // Pin to a valid org: keep the stored one if the user still belongs to it, else first.
      setActiveOrgState((cur) => {
        const ok = next.memberships.some((m) => m.org_id === cur);
        return ok ? cur : (next.memberships[0]?.org_id ?? null);
      });
    } catch {
      setMe(null); // 401 → not signed in
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (activeOrg) localStorage.setItem(ORG_KEY, activeOrg);
    else localStorage.removeItem(ORG_KEY);
  }, [activeOrg]);

  const setActiveOrg = useCallback((orgId: string) => {
    setApiOrg(orgId);
    setActiveOrgState(orgId);
  }, []);

  const logout = useCallback(async (everywhere = false) => {
    await (everywhere ? apiLogoutAll() : apiLogout()).catch(() => {});
    setMe(null);
    setActiveOrgState(null);
  }, []);

  const role = useMemo(
    () => me?.memberships.find((m) => m.org_id === activeOrg)?.role ?? null,
    [me, activeOrg],
  );

  const value: AuthState = {
    ready,
    user: me?.user ?? null,
    memberships: me?.memberships ?? [],
    activeOrg,
    role,
    isAdmin: role != null && ADMIN.includes(role),
    setActiveOrg,
    refresh,
    logout,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used within AuthProvider");
  return v;
}

// A soft 401 from anywhere in the api layer routes here. We can't use the router hook
// outside a component, so this hangs a listener that flips a bit the guard reads.
export function useAuthRedirect() {
  const { refresh } = useAuth();
  useEffect(() => {
    setUnauthorizedHandler(() => { void refresh(); });
    return () => setUnauthorizedHandler(() => {});
  }, [refresh]);
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { ready, user } = useAuth();
  const loc = useLocation();
  if (!ready) return <div className="auth-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { ready, user, isAdmin } = useAuth();
  if (!ready) return <div className="auth-loading">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (!isAdmin) return <Navigate to="/calls" replace />;
  return <>{children}</>;
}

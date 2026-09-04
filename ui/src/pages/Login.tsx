import { useEffect, useState, type FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { acceptInvite, getAuthConfig, login, signup, type AuthConfig } from "../api";
import { useAuth } from "../auth";

type Mode = "login" | "signup" | "invite";

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const [params] = useSearchParams();
  const { refresh, user, ready } = useAuth();
  const inviteToken = loc.pathname === "/accept-invite" ? params.get("token") : null;

  const [cfg, setCfg] = useState<AuthConfig | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [orgName, setOrgName] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Already signed in? Skip the form.
  useEffect(() => { if (ready && user && !inviteToken) nav("/calls", { replace: true }); },
    [ready, user, inviteToken, nav]);

  useEffect(() => {
    getAuthConfig().then((c) => {
      setCfg(c);
      // Dev prefill: one-click sign-in against the seeded account. Still the real flow.
      if (c.dev_open && c.dev_email && !inviteToken) {
        setEmail(c.dev_email);
        if (c.dev_password) setPassword(c.dev_password);
      }
    }).catch(() => setCfg({ dev_open: false, signup_open: false, dev_email: null, dev_password: null }));
  }, [inviteToken]);

  const mode: Mode = inviteToken ? "invite" : cfg?.signup_open ? "signup" : "login";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "invite") await acceptInvite(inviteToken!, password, name || undefined);
      else if (mode === "signup") await signup(email, password, orgName || undefined, name || undefined);
      else await login(email, password);
      await refresh();
      nav("/calls", { replace: true });
    } catch (err) {
      setError(mode === "login" ? "Invalid email or password." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "invite" ? "Accept your invite"
    : mode === "signup" ? "Create owner account" : "Sign in";
  const desc = mode === "invite" ? "Set a password to activate your account."
    : mode === "signup" ? "First run — create the owner account and your organization."
    : "Enter your credentials to access your workspace.";

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-hd">
          <img className="logo" src="/actioneer-logo.svg" alt="Actioneer" />
          <h2>{title}</h2>
          <p>{desc}</p>
        </div>
        <div className="auth-body">
          {mode !== "invite" && (
            <div className="field">
              <label htmlFor="email">Email</label>
              <input id="email" type="email" autoComplete="username" required
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="you@company.com" />
            </div>
          )}
          {mode === "signup" && (
            <>
              <div className="field">
                <label htmlFor="name">Your name</label>
                <input id="name" value={name} onChange={(e) => setName(e.target.value)}
                  placeholder="Optional" />
              </div>
              <div className="field">
                <label htmlFor="org">Organization</label>
                <input id="org" value={orgName} onChange={(e) => setOrgName(e.target.value)}
                  placeholder="Acme Inc." />
              </div>
            </>
          )}
          {mode === "invite" && (
            <div className="field">
              <label htmlFor="name">Your name</label>
              <input id="name" value={name} onChange={(e) => setName(e.target.value)}
                placeholder="Optional" />
            </div>
          )}
          <div className="field">
            <label htmlFor="password">Password</label>
            <input id="password" type="password"
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              required value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••" />
          </div>
          {error && <div className="auth-error">{error}</div>}
        </div>
        <div className="auth-foot">
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "…" : title}
          </button>
          {cfg?.dev_open && mode === "login" && (
            <span className="auth-hint">Dev mode — credentials prefilled.</span>
          )}
        </div>
      </form>
    </div>
  );
}

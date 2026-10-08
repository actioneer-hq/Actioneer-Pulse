import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getNotifications, type AnalysisNote, type StageBar } from "../api";
import { useActiveAgent } from "../ActiveAgentProvider";
import { useAuth } from "../auth";

// Top-right bell: rings (badge + pulse) when a stage of an analysis finishes — decision model, LLM,
// training data (if on), clustering, script improvement. Open it for each analysis's stages as separate
// progress bars (they run in different workers, so they move independently).

const ORDER = ["decision", "llm", "training", "clustering", "improve"] as const;
const SEEN_KEY = "pulse.notifications.seen";

function readSeen(): string {
  try { return localStorage.getItem(SEEN_KEY) ?? ""; } catch { return ""; }
}
function writeSeen(at: string) {
  try { localStorage.setItem(SEEN_KEY, at); } catch { /* private window: the badge just won't persist */ }
}

function Bar({ s }: { s: StageBar }) {
  if (s.state === "off") return null;
  const counted = s.total > 0;
  const pct = s.state === "done" ? 100 : counted ? Math.round((100 * s.done) / s.total) : 0;
  const right = s.state === "done" ? (counted ? `${s.done}/${s.total} · done` : s.note ?? "done")
    : s.state === "skipped" || s.state === "failed" ? `${s.state}${s.note ? ` · ${s.note}` : ""}`
    : s.state === "waiting" ? "waiting" : counted ? `${s.done}/${s.total}` : "running…";
  return (
    <div className={`nb-stage ${s.state}`}>
      <div className="nb-row"><span>{s.label}</span><span className="dimtxt">{right}</span></div>
      <div className="nb-bar"><span style={{ width: `${pct}%` }} /></div>
    </div>
  );
}

export default function NotificationBell() {
  const { activeOrg } = useAuth();
  const { setActiveAgent } = useActiveAgent();
  const navigate = useNavigate();
  const [items, setItems] = useState<AnalysisNote[]>([]);
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState(readSeen);
  const ref = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    getNotifications().then((r) => setItems(r.items)).catch(() => undefined);
  }, []);
  useEffect(() => { load(); }, [load, activeOrg]);
  const busy = items.some((i) => !i.complete);
  useEffect(() => {
    const t = setInterval(load, busy ? 4000 : 30000);
    return () => clearInterval(t);
  }, [busy, load]);
  useEffect(() => {  // close on outside click
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [open]);

  const events = items.flatMap((i) => i.events);
  const latest = events.reduce((m, e) => (e.at > m ? e.at : m), "");
  const unseen = events.filter((e) => e.at > seen).length;

  function toggle() {
    setOpen((o) => !o);
    if (!open && latest) { writeSeen(latest); setSeen(latest); }
  }
  function goto(i: AnalysisNote, path: string) {
    if (i.agent_id) setActiveAgent(i.agent_id);
    setOpen(false);
    navigate(path);
  }

  return (
    <div className="nb" ref={ref}>
      <button className={`nb-btn ${unseen ? "ring" : ""}`} onClick={toggle} aria-label="Analysis notifications"
        title="Analysis progress">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {unseen > 0 && <span className="nb-badge">{unseen}</span>}
        {busy && !unseen && <span className="nb-dot" />}
      </button>
      {open && (
        <div className="nb-panel">
          <div className="nb-hd">Analysis</div>
          {items.length === 0 && <p className="dimtxt">No analyses yet — upload calls on the Projects page.</p>}
          {items.map((i) => (
            <div key={i.id} className="nb-item">
              <div className="nb-row">
                <b>{i.agent ?? "Project"}</b>
                <span className="dimtxt">{i.calls} calls · {i.complete ? "complete" : "in progress"}</span>
              </div>
              {ORDER.map((k) => <Bar key={k} s={i.stages[k]} />)}
              <div className="nb-links">
                <button onClick={() => goto(i, "/analysis")}>Open analysis</button>
                {i.stages.improve.state === "done" && (
                  <button onClick={() => goto(i, "/settings/agents")}>See improved script</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

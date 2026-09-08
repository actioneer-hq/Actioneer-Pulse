import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { listAgents, listCalls, type Agent, type Call } from "../api";
import { useAuth } from "../auth";
import { useBackfill } from "../BackfillProvider";
import CallDetail from "../components/CallDetail";
import CallTable from "../components/CallTable";
import { ms, pct } from "../format";

// Analysed is the worker's stamp (metric_version), not Call.status: a spans-only
// call stays "awaiting_media" forever even after its turns are fully measured.
const TABS: [string, string, (c: Call) => boolean][] = [
  ["all", "All", () => true],
  ["analysed", "Analysed", (c) => c.analysed],
  ["pending", "Not analysed yet", (c) => !c.analysed && c.status !== "unsupported"],
  ["failed", "Failed", (c) => c.status === "failed"],
  ["unsupported", "Unsupported", (c) => c.status === "unsupported"],
];

export default function Calls() {
  const { activeOrg } = useAuth();
  const { analyzedCalls } = useBackfill();
  const [fetched, setFetched] = useState<Call[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get("tab") ?? "all";
  const setTab = (t: string) =>
    setSearchParams((p) => { p.set("tab", t); return p; }, { replace: true });
  const [q, setQ] = useState("");

  // Re-fetch whenever the active org or agent filter changes; the api layer sends the
  // matching X-Voiceobs-Org header so results stay scoped.
  useEffect(() => {
    setError(null);
    listCalls(200, agentId || undefined)
      .then(setFetched)
      .catch((e: Error) => setError(e.message));
  }, [activeOrg, agentId]);

  useEffect(() => {
    listAgents().then(setAgents).catch(() => setAgents([]));
  }, [activeOrg]);

  // Merge live backfill results: prepend the newest, and replace any fetched row with the
  // same id (so a call already listed is updated in place rather than duplicated).
  const calls = useMemo(() => {
    if (!analyzedCalls.length) return fetched;
    const live = new Map(analyzedCalls.map((c) => [c.id, c]));
    const merged = fetched.map((c) => live.get(c.id) ?? c);
    const seen = new Set(fetched.map((c) => c.id));
    const fresh = analyzedCalls.filter((c) => !seen.has(c.id));
    return [...fresh, ...merged];
  }, [fetched, analyzedCalls]);

  const byTab = useMemo(() => {
    const m: Record<string, Call[]> = {};
    for (const [k, , f] of TABS) m[k] = calls.filter(f);
    return m;
  }, [calls]);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const base = byTab[tab] ?? calls;
    if (!needle) return base;
    return base.filter((c) =>
      [c.id, c.source, c.environment, c.status, ...Object.values(c.labels)]
        .join(" ").toLowerCase().includes(needle),
    );
  }, [byTab, tab, q, calls]);

  // j / k walk the visible rows, Esc closes the inspector. Skipped while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      const i = rows.findIndex((c) => c.id === selected);
      if (e.key === "j" && i < rows.length - 1) setSelected(rows[i + 1].id);
      else if (e.key === "k" && i > 0) setSelected(rows[i - 1].id);
      else if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, selected]);

  const allTurns = calls.reduce((a, c) => a + c.turns, 0);
  const bargeIns = calls.reduce((a, c) => a + c.barge_ins, 0);
  const tiles: [string, string, string?][] = [
    ["Calls", String(calls.length)],
    ["Median call p50 v2v", ms(pct(calls.map((c) => c.p50_v2v_ms), 0.5)), "median of per-call medians"],
    ["p95 of call p50s", ms(pct(calls.map((c) => c.p50_v2v_ms), 0.95))],
    ["Barge-in rate", allTurns ? `${+((100 * bargeIns) / allTurns).toFixed(1)}%` : "—"],
    ["Without audio", String(calls.filter((c) => !c.media_ready).length), "measured from spans only"],
  ];

  return (
    <div className="page">
      <div className="list">
        <div className="head">
          <h1>Calls</h1>
          <div className="sub">Every call Pulse has ingested, spans and audio joined into one record.</div>
        </div>
        <div className="tiles">
          {tiles.map(([l, v, s]) => (
            <div className="tile" key={l}><span>{l}</span><b>{v}</b>{s && <small>{s}</small>}</div>
          ))}
        </div>
        <div className="tabs">
          {TABS.map(([k, l]) => (
            <button key={k} className={tab === k ? "on" : undefined} onClick={() => setTab(k)}>
              {l}<em>{byTab[k]?.length ?? 0}</em>
            </button>
          ))}
        </div>
        <div className="tools">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, source, label…" />
          {agents.length > 0 && (
            <select className="agent-filter" value={agentId}
              onChange={(e) => setAgentId(e.target.value)}>
              <option value="">All agents</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          )}
          <span className="count">{error ?? `${rows.length} call${rows.length === 1 ? "" : "s"}`}</span>
        </div>
        <CallTable calls={rows} selected={selected} onSelect={setSelected} />
      </div>
      {selected && <CallDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

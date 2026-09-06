import { useEffect, useMemo, useState } from "react";
import {
  getBoardsSummary, listAgents, streamBoards,
  type Agent, type BoardSnapshot,
} from "../api";
import { useAuth } from "../auth";
import { ms } from "../format";
import { AreaCard, CHART_COLORS, DonutCard, LineCard } from "../components/boards/Charts";

const RANGES: [string, string][] = [["24h", "24h"], ["7d", "7d"], ["30d", "30d"]];
const DISPO_LABEL: Record<string, string> = {
  connected: "Connected", no_answer: "No answer", unknown: "Unknown", none: "Not judged",
};

const pctFmt = (v: number) => `${v.toFixed(0)}%`;
const rateTile = (r: number) => `${(r * 100).toFixed(1)}%`;
// cost is raw currency units (often sub-unit per call) — keep precision so it isn't rounded to 0.
const money = (v: number) => (v === 0 ? "0" : v >= 1 ? v.toFixed(2) : v.toPrecision(2));

// short x-axis label per range: 24h → hour, else month/day
const labeller = (range: string) => (iso: string) => {
  const d = new Date(iso);
  return range === "24h"
    ? `${String(d.getHours()).padStart(2, "0")}:00`
    : `${d.getMonth() + 1}/${d.getDate()}`;
};

export default function Boards() {
  const { activeOrg } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState("");
  const [range, setRange] = useState("7d");
  const [snap, setSnap] = useState<BoardSnapshot | null>(null);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgents().then(setAgents).catch(() => setAgents([]));
  }, [activeOrg]);

  // Instant paint via REST, then hold a live SSE that pushes a fresh snapshot on every change.
  useEffect(() => {
    setError(null);
    setLive(false);
    const filters = { agent_id: agentId || undefined, range };
    getBoardsSummary(filters).then(setSnap).catch((e: Error) => setError(e.message));
    const stop = streamBoards(filters, (s) => { setSnap(s); setLive(true); }, () => setLive(false));
    return stop;
  }, [activeOrg, agentId, range]);

  const rows = useMemo(() => {
    if (!snap) return [];
    const t = labeller(snap.range);
    return snap.buckets.map((iso, i) => ({
      t: t(iso),
      volume: snap.volume[i],
      failRate: +(snap.failure.rate[i] * 100).toFixed(1),
      p50: snap.latency.p50[i],
      p95: snap.latency.p95[i],
      grRate: +(snap.guardrail.rate[i] * 100).toFixed(1),
      toolCalls: snap.tools.calls[i],
      toolErrors: snap.tools.errors[i],
      cost: snap.cost.total[i],
    }));
  }, [snap]);

  const dispo = useMemo(() => {
    if (!snap) return [];
    return Object.entries(snap.disposition)
      .filter(([, v]) => v > 0)
      .map(([k, v], i) => ({ name: DISPO_LABEL[k] ?? k, value: v, color: CHART_COLORS[i % 6] }));
  }, [snap]);

  const t = snap?.totals;
  const tiles: [string, string, string?][] = [
    ["Calls", t ? String(t.calls) : "—"],
    ["Failure rate", t ? rateTile(t.failure_rate) : "—"],
    ["p50 latency", t ? ms(t.p50_ms) : "—"],
    ["p95 latency", t ? ms(t.p95_ms) : "—"],
    ["Guardrail violations", t ? rateTile(t.violation_rate) : "—"],
    ["Tool-call errors", t ? rateTile(t.tool_error_rate) : "—", t ? `${t.tool_calls} calls` : undefined],
    ["Cost", t ? money(t.cost_total) : "—", "sum over range"],
  ];

  return (
    <div className="page">
      <div className="list">
        <div className="head">
          <h1>Boards <span className={`live-dot ${live ? "on" : ""}`} title={live ? "live" : "connecting…"} /></h1>
          <div className="sub">Live metrics across your voice agents — updates as calls are ingested.</div>
        </div>
        <div className="tiles">
          {tiles.map(([l, v, s]) => (
            <div className="tile" key={l}><span>{l}</span><b>{v}</b>{s && <small>{s}</small>}</div>
          ))}
        </div>
        <div className="tools">
          <div className="seg">
            {RANGES.map(([k, l]) => (
              <button key={k} className={range === k ? "on" : undefined} onClick={() => setRange(k)}>{l}</button>
            ))}
          </div>
          <select className="agent-filter" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">All agents</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <span className="count">{error ?? (snap ? `${snap.totals.calls} calls` : "loading…")}</span>
        </div>

        <div className="board-grid">
          <AreaCard title="Call volume" data={rows} series={[{ key: "volume", label: "Calls", color: "var(--chart-1)" }]} />
          <LineCard title="Failure rate" data={rows} fmtY={pctFmt}
            series={[{ key: "failRate", label: "Failure %", color: "var(--chart-3)" }]} />
          <LineCard title="Latency (voice-to-voice)" data={rows} fmtY={(v) => ms(v)}
            series={[
              { key: "p50", label: "p50", color: "var(--chart-1)" },
              { key: "p95", label: "p95", color: "var(--chart-4)" },
            ]} />
          <DonutCard title="Disposition mix" data={dispo} />
          <LineCard title="Guardrail-violation rate" data={rows} fmtY={pctFmt}
            series={[{ key: "grRate", label: "Violation %", color: "var(--chart-3)" }]} />
          <LineCard title="Tool calls & errors" data={rows}
            series={[
              { key: "toolCalls", label: "Tool calls", color: "var(--chart-1)" },
              { key: "toolErrors", label: "Errors", color: "var(--unknown)" },
            ]} />
          <AreaCard title="Cost" data={rows} fmtY={money}
            series={[{ key: "cost", label: "Cost", color: "var(--chart-2)" }]} />
        </div>
      </div>
    </div>
  );
}

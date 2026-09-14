import { useEffect, useMemo, useState } from "react";
import {
  CLUSTER_LEVERS, downloadTraining, getArchetypes, getClusters,
  type ArchetypeView, type ClusterView,
} from "../api";
import { useActiveAgent } from "../ActiveAgentProvider";
import { useAuth } from "../auth";
import CallDetail from "../components/CallDetail";
import { ScatterCard } from "../components/boards/Charts";

const RANGES: [string, string][] = [["7d", "7d"], ["30d", "30d"], ["90d", "90d"], ["", "All"]];

export default function Clusters() {
  const { activeOrg } = useAuth();
  const { activeAgent } = useActiveAgent();
  const [range, setRange] = useState("90d");
  const [views, setViews] = useState<Record<string, ClusterView>>({});
  const [arche, setArche] = useState<ArchetypeView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  async function runExport(format: "sft" | "dpo") {
    setExporting(true);
    try {
      await downloadTraining(format, activeAgent || undefined, range || undefined);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

  useEffect(() => {
    setError(null);
    const filters = { agent_id: activeAgent || undefined, range: range || undefined };
    for (const [lever] of CLUSTER_LEVERS) {
      getClusters(lever, filters)
        .then((v) => setViews((prev) => ({ ...prev, [lever]: v })))
        .catch((e: Error) => {
          setError(e.message);
          // resolve the panel to an empty view so it doesn't spin forever
          setViews((prev) => ({ ...prev, [lever]: { lever, clusters: [], points: [] } }));
        });
    }
    getArchetypes(filters).then(setArche).catch(() => setArche(null));
  }, [activeOrg, activeAgent, range]);

  const totalCalls = useMemo(
    () => Math.max(...Object.values(views).map((v) => v.points.length), 0),
    [views],
  );

  return (
    <div className="page">
      <div className="list">
        <div className="head">
          <h1>Clusters</h1>
          <div className="sub">Recurring patterns in the analysis prose — themes per lever, and the
            cross-lever archetypes that co-occur.</div>
        </div>
        <div className="tools">
          <div className="seg">
            {RANGES.map(([k, l]) => (
              <button key={l} className={range === k ? "on" : undefined} onClick={() => setRange(k)}>{l}</button>
            ))}
          </div>
          <span className="count">{error ?? `${totalCalls} calls`}</span>
          <div className="export-group" title="Download the LLM corrections as training data for the selected agent">
            <span className="export-label">Export training data</span>
            <button disabled={exporting} onClick={() => runExport("sft")}>SFT</button>
            <button disabled={exporting} onClick={() => runExport("dpo")}>DPO</button>
          </div>
        </div>

        <div className="scroll">
          <div className="board-grid">
            {CLUSTER_LEVERS.map(([lever, title]) => {
              const v = views[lever];
              if (v && v.points.length > 0) {
                return <ScatterCard key={lever} title={title} view={v} onSelect={setSelected} />;
              }
              return (
                <div key={lever} className="panel-card board-card"><h3>{title}</h3>
                  <p className="dimtxt">{v ? "No clusters yet." : "Loading…"}</p></div>
              );
            })}
          </div>

          <Archetypes arche={arche} />
        </div>
      </div>
      {selected && <CallDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

// Each archetype is a recurring end-to-end failure mode. Read it as a sentence: N calls where
// <root cause> → fixed by <fix>, blamed on <fault>, ending <outcome>. Lift = how strongly those
// pieces co-occur vs. chance (a real pattern, not a coincidence).
const OBJECTIVE: Record<string, { label: string; cls: string }> = {
  yes: { label: "objective met", cls: "ok" },
  partial: { label: "partly met", cls: "warn" },
  no: { label: "objective not met", cls: "bad" },
  unknown: { label: "outcome unknown", cls: "" },
};
const FAULT_LABEL: Record<string, string> = {
  none: "no model fault", asr: "ASR fault", llm: "LLM fault", tts: "TTS fault", other: "other fault",
};
const FAULT_COLOR: Record<string, string> = {
  asr: "var(--chart-1)", llm: "var(--chart-3)", tts: "var(--chart-4)",
  other: "var(--chart-6)", none: "var(--ok)",
};

function Archetypes({ arche }: { arche: ArchetypeView | null }) {
  if (!arche || arche.archetypes.length === 0) {
    return (
      <div className="panel-card" style={{ marginTop: 16 }}>
        <h3>Recurring failure modes <span className="right">across levers</span></h3>
        <p className="dimtxt">Nothing recurring yet — a pattern appears once several calls share the
          same root-cause theme <em>and</em> fix.</p>
      </div>
    );
  }
  return (
    <div className="arch-wrap">
      <div className="arch-head">
        <h3>Recurring failure modes</h3>
        <p className="dimtxt">Each card is one pattern that shows up across many calls — the root cause,
          the fix that addresses it, who's at fault, and how it ends. Ranked by how many calls follow it.</p>
      </div>
      <div className="arch-grid">
        {arche.archetypes.map((a, i) => {
          const fault = a.combo.model_fault ?? "none";
          const obj = OBJECTIVE[a.combo.objective_achieved] ?? OBJECTIVE.unknown;
          const pct = a.consistency != null ? Math.round(a.consistency * 100) : null;
          return (
            <div className="arch-card" key={i}>
              <div className="arch-top">
                <span className="arch-count"><b>{a.count}</b> calls</span>
                <span className="arch-tags">
                  <span className="arch-fault">
                    <span className="dot" style={{ background: FAULT_COLOR[fault] ?? "var(--dim)" }} />
                    {FAULT_LABEL[fault] ?? fault}
                  </span>
                  {obj.cls
                    ? <span className={`pill ${obj.cls}`}>{obj.label}</span>
                    : <span className="pill">{obj.label}</span>}
                </span>
              </div>
              <div className="arch-cause">{a.combo.root_cause}</div>
              <div className="arch-arrow">↓ recommended fix</div>
              <div className="arch-fix">{a.combo.suggested_fix}</div>
              {pct != null && (
                <div className="arch-strength"
                  title={`${a.count} of ${a.cause_total} calls with this root cause follow this exact path`}>
                  <span className="arch-meter">
                    <span className="on" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="arch-lift">
                    <b>{pct}%</b> of calls with this cause end this way
                  </span>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

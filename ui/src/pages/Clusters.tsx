import { useEffect, useMemo, useState } from "react";
import {
  CLUSTER_LEVERS, getArchetypes, getClusters, listAgents,
  type Agent, type ArchetypeView, type ClusterView,
} from "../api";
import { useAuth } from "../auth";
import CallDetail from "../components/CallDetail";
import { ScatterCard } from "../components/boards/Charts";

const RANGES: [string, string][] = [["7d", "7d"], ["30d", "30d"], ["90d", "90d"], ["", "All"]];
const DIM_LABEL: Record<string, string> = {
  root_cause: "Root-cause theme", suggested_fix: "Fix theme",
  model_fault: "Model fault", objective_achieved: "Objective",
};

export default function Clusters() {
  const { activeOrg } = useAuth();
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState("");
  const [range, setRange] = useState("90d");
  const [views, setViews] = useState<Record<string, ClusterView>>({});
  const [arche, setArche] = useState<ArchetypeView | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgents().then(setAgents).catch(() => setAgents([]));
  }, [activeOrg]);

  useEffect(() => {
    setError(null);
    const filters = { agent_id: agentId || undefined, range: range || undefined };
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
  }, [activeOrg, agentId, range]);

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
          <select className="agent-filter" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">All agents</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <span className="count">{error ?? `${totalCalls} calls`}</span>
        </div>

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

        <ArchetypeTable arche={arche} onSelect={() => { /* row-drill: future */ }} />
      </div>
      {selected && <CallDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function ArchetypeTable({ arche }: { arche: ArchetypeView | null; onSelect: () => void }) {
  if (!arche || arche.archetypes.length === 0) {
    return (
      <div className="panel-card" style={{ marginTop: 16 }}>
        <h3>Archetypes <span className="right">cross-lever</span></h3>
        <p className="dimtxt">No recurring archetypes yet — they appear once enough calls share a
          combination of themes.</p>
      </div>
    );
  }
  return (
    <div className="panel-card" style={{ marginTop: 16 }}>
      <h3>Archetypes <span className="right">recurring combinations across levers</span></h3>
      <table>
        <thead>
          <tr>
            {arche.dims.map((d) => <th key={d}>{DIM_LABEL[d] ?? d}</th>)}
            <th className="r">Calls</th><th className="r">Lift</th>
          </tr>
        </thead>
        <tbody>
          {arche.archetypes.map((a, i) => (
            <tr key={i}>
              {arche.dims.map((d) => <td key={d}>{a.combo[d]}</td>)}
              <td className="r strong">{a.count}</td>
              <td className="r dimtxt">{a.lift ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

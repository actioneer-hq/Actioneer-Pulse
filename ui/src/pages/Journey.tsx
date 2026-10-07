import { useEffect, useState } from "react";
import { useActiveAgent } from "../ActiveAgentProvider";
import { getJourneyFunnel, type JourneyFunnel } from "../api";

// The selected project's funnel for its active script version: how far calls get, what customers do
// and whether the agent handles it (by cause), guardrails broken, and script gaps to fix.

const CAUSES: [string, string][] = [
  ["script_gap", "Script gap — fix the script"],
  ["not_followed", "Not followed — model / training data"],
];

const pct = (n: number, d: number) => (d ? `${Math.round((100 * n) / d)}%` : "—");

export default function Journey() {
  const { activeAgent } = useActiveAgent();
  const [f, setF] = useState<JourneyFunnel | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeAgent) return;
    setF(null);
    getJourneyFunnel(activeAgent).then(setF).catch((e: Error) => setError(e.message));
  }, [activeAgent]);

  if (error) return <div className="page"><div className="auth-error">{error}</div></div>;
  if (!f) return <div className="page"><div className="dimtxt">Loading…</div></div>;
  if (!f.calls) {
    return (
      <div className="page"><div className="list"><div className="head"><h1>Journey</h1>
        <div className="sub">{f.status === "ready"
          ? "No calls judged against this script version yet."
          : "This project's journey isn't ready yet — set the script on the Projects page."}</div>
      </div></div></div>
    );
  }
  const human = f.human ?? 0;
  const maxReach = Math.max(1, ...(f.stages ?? []).map((s) => s.reached));
  return (
    <div className="page">
      <div className="list journey-page">
        <div className="head">
          <h1>Journey</h1>
          <div className="sub">Script v{f.version} · {f.calls} calls judged · {human} with a person
            · {f.short} short (≤3 customer turns)</div>
        </div>

        <div className="tiles">
          <div className="tile"><span>Achieved</span><b>{pct(f.objective?.achieved ?? 0, human)}</b></div>
          <div className="tile"><span>Partial</span><b>{pct(f.objective?.partial ?? 0, human)}</b></div>
          <div className="tile"><span>Not achieved</span><b>{pct(f.objective?.not_achieved ?? 0, human)}</b></div>
          {CAUSES.map(([k, label]) => (
            <div className="tile" key={k} title={label}><span>{label.split(" — ")[0]}</span>
              <b>{f.causes?.[k] ?? 0}</b><small>failures</small></div>
          ))}
        </div>

        <h3>Funnel</h3>
        <div className="funnel">
          {(f.stages ?? []).map((s) => (
            <div key={s.stage} className="funnel-row">
              <span className="funnel-label">{s.stage}</span>
              <span className="funnel-bar"><span style={{ width: `${(100 * s.reached) / maxReach}%` }} /></span>
              <span className="funnel-n">{s.reached} · {pct(s.reached, human)}</span>
            </div>
          ))}
        </div>

        <h3>Failures</h3>
        <table className="jtable">
          <thead><tr><th>What failed</th><th>Kind</th><th>Cause</th><th className="r">Calls</th></tr></thead>
          <tbody>
            {(f.failures ?? []).map((x, i) => (
              <tr key={i}><td>{x.item}</td><td className="dimtxt">{x.kind}</td>
                <td><span className={`cause-chip ${x.cause}`}>{x.cause.replace("_", " ")}</span></td>
                <td className="r">{x.calls}</td></tr>
            ))}
            {!f.failures?.length && <tr><td colSpan={4} className="dimtxt">No failures yet.</td></tr>}
          </tbody>
        </table>

        <h3>What customers did</h3>
        <table className="jtable">
          <thead><tr><th>Situation</th><th>Stage</th><th className="r">Happened</th><th className="r">Not handled</th>
            <th className="r">Script gap</th><th className="r">Not followed</th></tr></thead>
          <tbody>
            {(f.branches ?? []).map((b, i) => (
              <tr key={i}>
                <td>{b.if}{b.not_in_script ? <span className="cause-chip script_gap">not in script</span> : null}</td>
                <td className="dimtxt">{b.stage ?? "any time"}</td>
                <td className="r">{b.happened ?? 0}</td>
                <td className="r">{b.not_handled ?? 0}</td>
                <td className="r">{b["cause:script_gap"] ?? 0}</td>
                <td className="r">{b["cause:not_followed"] ?? 0}</td>
              </tr>
            ))}
            {!f.branches?.length && <tr><td colSpan={6} className="dimtxt">No customer situations detected yet.</td></tr>}
          </tbody>
        </table>

        <h3>Guardrails broken</h3>
        <table className="jtable">
          <thead><tr><th>Rule</th><th className="r">Calls</th><th className="r">Script gap</th>
            <th className="r">Not followed</th></tr></thead>
          <tbody>
            {(f.guardrails ?? []).map((g, i) => (
              <tr key={i}><td>{g.rule}</td><td className="r">{g.broken}</td>
                <td className="r">{g["cause:script_gap"] ?? 0}</td><td className="r">{g["cause:not_followed"] ?? 0}</td></tr>
            ))}
            {!f.guardrails?.length && <tr><td colSpan={4} className="dimtxt">No guardrails broken.</td></tr>}
          </tbody>
        </table>

        <h3>Script gaps</h3>
        <ul className="gaps">
          {f.standard?.callback_not_in_script ? <li>Callback requests — {f.standard.callback_not_in_script} calls,
            the script has no instruction for them.</li> : null}
          {f.standard?.escalation_not_in_script ? <li>Requests for a human — {f.standard.escalation_not_in_script} calls,
            the script has no instruction for them.</li> : null}
          {(f.unscripted ?? []).map(([what, n], i) => <li key={i}>{what} — {n} calls</li>)}
          {!f.unscripted?.length && !f.standard?.callback_not_in_script && !f.standard?.escalation_not_in_script &&
            <li className="dimtxt">None found.</li>}
        </ul>
      </div>
    </div>
  );
}

import { Tab, TabList, Tabs } from "@actioneer/ads";
import { Fragment, useEffect, useState } from "react";
import {
  getClusters, getJourneyFunnel,
  type ClusterSample, type ClustersView, type FailureGroup, type GapPlacement, type GapPool, type JourneyFunnel,
} from "../api";
import { useActiveAgent } from "../ActiveAgentProvider";
import { useAuth } from "../auth";
import CallDetail from "../components/CallDetail";

// One page for the project's active script version:
// 1. Script journey — how far calls get through the script's stages, and the outcome split.
// 2. Not followed — what the script covers that the agent didn't do, ranked by impact (how often x how
//    much it lowers the objective rate); each row expands into its details and the lines behind it.
// 3. Script gaps — what the script doesn't cover: uncovered callback / human requests, and unscripted
//    themes split by whether the agent's improvised reply worked.

const RANGES: [string, string][] = [["7d", "7d"], ["30d", "30d"], ["90d", "90d"], ["", "All"]];
const KIND: Record<string, string> = {
  stage: "missed stage", branch: "customer situation", guardrail: "guardrail", standard: "callback / human",
  opening: "opening", closing: "closing",
};
const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);

function Samples({ samples, onOpen }: { samples: ClusterSample[]; onOpen: (id: string) => void }) {
  return (
    <div className="cl-samples">
      {samples.map((s, i) => (
        <button key={i} className="cl-sample" disabled={!s.call_id}
          onClick={() => s.call_id && onOpen(s.call_id)} title="Open the call">
          {s.what ? <>{s.what} <span className="dimtxt">— “{s.text}” · turn {s.turn}</span></>
            : <>“{s.text}” <span className="dimtxt">· turn {s.turn}</span></>}
        </button>
      ))}
    </div>
  );
}

const CATEGORY: Record<string, string> = {
  branch: "branch", anytime: "anytime situation", guardrail: "guardrail", fact: "missing fact",
  escalation: "escalation", off_topic: "off-topic",
};
function placementLabel(p: GapPlacement): string {
  const cat = CATEGORY[p.category ?? ""] ?? p.category;
  if (p.category === "off_topic") return "off-topic — no script change";
  if (p.match) return `covered by: ${p.match}`;
  return `new ${cat}${p.stage ? ` · in ${p.stage}` : ""}`;
}

function GapThemes({ title, pool, onOpen }: { title: string; pool: GapPool; onOpen: (id: string) => void }) {
  if (!pool.calls) return null;
  return (
    <>
      <div className="jr-hd">{title} <span className="dimtxt">· {pool.calls} calls</span></div>
      <div className="cl-themes">
        {pool.themes.map((v) => (
          <div key={v.key} className="panel-card cl-theme">
            <div className="cl-vhead"><b>{v.name ?? "Unnamed"}</b> <span className="dimtxt">· {v.calls} calls</span></div>
            {v.placement?.category && <div className="cl-place">{placementLabel(v.placement)}</div>}
            <Samples samples={v.samples} onOpen={onOpen} />
          </div>
        ))}
      </div>
      {pool.other_calls > 0 && <p className="dimtxt">+ {pool.other_calls} calls with one-off moments
        {pool.themes.length ? "" : " — themes appear once a moment recurs across enough calls"}.</p>}
    </>
  );
}

function FailureRows({ rows, cameUp, onOpen }: {
  rows: FailureGroup[]; cameUp: Record<string, number>; onOpen: (id: string) => void;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const maxImpact = Math.max(0.0001, ...rows.map((f) => f.impact));
  const toggle = (k: string) => setOpen((s) => {
    const n = new Set(s);
    if (n.has(k)) n.delete(k); else n.add(k);
    return n;
  });
  return (
    <table className="jtable cl-table">
      <thead><tr><th>What failed</th><th>Kind</th><th className="r">Calls</th>
        <th className="r">Objective met · with / without</th><th>Impact</th></tr></thead>
      <tbody>
        {rows.map((f) => {
          const k = `${f.kind}|${f.item}`;
          const isOpen = open.has(k);
          const came = f.kind === "branch" ? cameUp[f.item] : undefined;
          return (
            <Fragment key={k}>
              <tr className="cl-row expandable" onClick={() => toggle(k)}>
                <td><span className="chev">{isOpen ? "▾" : "▸"}</span>{f.item}</td>
                <td className="dimtxt">{KIND[f.kind] ?? f.kind}</td>
                <td className="r">{f.calls} <span className="dimtxt">({pct(f.share)})</span></td>
                <td className="r">{pct(f.achieved_with)} / {pct(f.achieved_without)}</td>
                <td><span className="cl-impact"><span style={{ width: `${(100 * f.impact) / maxImpact}%` }} /></span></td>
              </tr>
              {isOpen && (
                <tr className="cl-variants"><td colSpan={5}>
                  <div className="cl-detail">
                    <span><b>{f.calls}</b> calls ({pct(f.share)} of calls with a person)</span>
                    {came != null && <span>came up in <b>{came}</b> calls</span>}
                    <span>objective met <b>{pct(f.achieved_with)}</b> with it vs <b>{pct(f.achieved_without)}</b> without</span>
                  </div>
                  {f.samples.length > 0 ? (
                    <>
                      <div className="jr-hd">Where it happened</div>
                      <Samples samples={f.samples} onOpen={onOpen} />
                    </>
                  ) : <div className="dimtxt">No lines located for this failure yet.</div>}
                </td></tr>
              )}
            </Fragment>
          );
        })}
        {!rows.length && <tr><td colSpan={5} className="dimtxt">Nothing in this range.</td></tr>}
      </tbody>
    </table>
  );
}

function Section({ title, note, count, children }: {
  title: string; note?: string; count?: number; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="an-section">
      <h3 className="sec-toggle" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="chev">{open ? "▾" : "▸"}</span>{title}
        {count != null && <span className="pill" style={{ marginLeft: 8 }}>{count}</span>}
        {note && <span className="dimtxt"> · {note}</span>}
      </h3>
      {open && children}
    </div>
  );
}

export default function Analysis() {
  const { activeOrg } = useAuth();
  const { activeAgent } = useActiveAgent();
  const [range, setRange] = useState("90d");
  const [view, setView] = useState<ClustersView | null>(null);
  const [progress, setProgress] = useState<JourneyFunnel | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeAgent) return;
    setError(null);
    setView(null);
    getClusters(activeAgent, range || undefined).then(setView).catch((e: Error) => setError(e.message));
    getJourneyFunnel(activeAgent).then(setProgress).catch(() => setProgress(null));
  }, [activeOrg, activeAgent, range]);

  const notFollowed = (view?.failures ?? []).filter((f) => f.cause === "not_followed");
  const gaps = (view?.failures ?? []).filter((f) => f.cause === "script_gap");
  const cameUp: Record<string, number> = {};
  for (const b of progress?.branches ?? []) cameUp[b.if] = (cameUp[b.if] ?? 0) + (b.happened ?? 0);
  const human = progress?.human ?? 0;
  const maxReach = Math.max(1, ...(progress?.stages ?? []).map((s) => s.reached));

  return (
    <div className="page">
      <div className="list clusters-page">
        <div className="head">
          <h1>Analysis</h1>
          <div className="sub">How calls move through the script, what the agent didn't follow — ranked by
            what it costs the objective — and what the script doesn't cover.</div>
        </div>
        <div className="tools">
          <Tabs value={range} onValueChange={setRange}>
            <TabList>{RANGES.map(([k, l]) => <Tab key={l} value={k}>{l}</Tab>)}</TabList>
          </Tabs>
          <span className="count">{error ?? (view ? `Script v${view.version ?? "—"} · ${view.human ?? 0} calls with a person` : "loading…")}</span>
        </div>

        <div className="scroll">
          {view?.status === "no_script" && <p className="dimtxt">This project has no script yet — set it on the Projects page.</p>}
          {view?.status === "no_embeddings" && <p className="dimtxt">Patterns need an embedding model (VOICEOBS_EMBEDDING_API_KEY).</p>}

          {view && view.status !== "no_script" && (
            <>
              <Section title="Script journey" note="how far calls get through the script">
              {progress && (progress.calls ?? 0) > 0 ? (
                <>
                  <div className="tiles">
                    <div className="tile"><span>Achieved</span><b>{pct(human ? (progress.objective?.achieved ?? 0) / human : null)}</b></div>
                    <div className="tile"><span>Partial</span><b>{pct(human ? (progress.objective?.partial ?? 0) / human : null)}</b></div>
                    <div className="tile"><span>Not achieved</span><b>{pct(human ? (progress.objective?.not_achieved ?? 0) / human : null)}</b></div>
                  </div>
                  <div className="funnel">
                    {(progress.stages ?? []).map((s) => (
                      <div key={s.stage} className="funnel-row">
                        <span className="funnel-label">{s.stage}</span>
                        <span className="funnel-bar"><span style={{ width: `${(100 * s.reached) / maxReach}%` }} /></span>
                        <span className="funnel-n">{s.reached} · {pct(human ? s.reached / human : null)}</span>
                      </div>
                    ))}
                  </div>
                </>
              ) : <p className="dimtxt">No calls judged against this script version yet.</p>}
              </Section>

              <Section title="Not followed" count={notFollowed.length}
                note="the script covers it, the agent didn't do it — click a row for details">
                <FailureRows rows={notFollowed} cameUp={cameUp} onOpen={setSelected} />
              </Section>

              <Section title="Script gaps" count={gaps.length + view.unscripted.not_handled.themes.length
                + view.unscripted.handled.themes.length} note="what the script doesn't cover">
                {gaps.length > 0 && <FailureRows rows={gaps} cameUp={cameUp} onOpen={setSelected} />}
                <GapThemes title="Agent struggled" pool={view.unscripted.not_handled} onOpen={setSelected} />
                <GapThemes title="Agent improvised OK" pool={view.unscripted.handled} onOpen={setSelected} />
                {!gaps.length && !view.unscripted.not_handled.calls && !view.unscripted.handled.calls &&
                  <p className="dimtxt">Nothing uncovered yet.</p>}
              </Section>
            </>
          )}
        </div>
      </div>
      {selected && <CallDetail id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

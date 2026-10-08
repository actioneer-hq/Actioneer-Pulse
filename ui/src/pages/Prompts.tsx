import { Button, InputField } from "@actioneer/ads";
import { useEffect, useState } from "react";
import {
  comparePrompts, getScriptLibrary,
  type LibraryImproved, type LibraryVersion, type PromptComparison, type RsiChange,
} from "../api";
import { useActiveAgent } from "../ActiveAgentProvider";
import { ms } from "../format";

function rate(value: number | null): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function money(value: number | null): string {
  return value == null ? "—" : value.toFixed(3);
}

// The project's scripts: every saved version and every improved script (additions / A / B), each with
// its text and its script journey JSON. The older campaign comparison sits below.
type Pick = { kind: "version"; v: LibraryVersion } | { kind: "improved"; r: LibraryImproved; variant: string };
const VARIANT: Record<string, string> = { additions: "Additions only", A: "A — revise", B: "B — restructure" };

export default function Prompts() {
  const { activeAgent } = useActiveAgent();
  const [lib, setLib] = useState<{ versions: LibraryVersion[]; improved: LibraryImproved[] } | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [tab, setTab] = useState<"text" | "json" | "changes">("text");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!activeAgent) return;
    setLib(null); setPick(null);
    getScriptLibrary(activeAgent).then((l) => {
      setLib(l);
      const active = l.versions.find((v) => v.active) ?? l.versions[0];
      if (active) setPick({ kind: "version", v: active });
    }).catch(() => setLib({ versions: [], improved: [] }));
  }, [activeAgent]);

  const shown = pick?.kind === "version"
    ? { title: `Script v${pick.v.version}${pick.v.active ? " (active)" : ""}`, text: pick.v.text, json: pick.v.journey,
        chars: pick.v.chars, changes: null as RsiChange[] | null, note: pick.v.journey_status === "ready" ? null
          : `script journey: ${pick.v.journey_status}` }
    : pick ? { title: `Improved from v${pick.r.base_version ?? "?"} · ${VARIANT[pick.variant] ?? pick.variant}`,
        text: pick.r.variants[pick.variant].text, json: pick.r.variants[pick.variant].journey,
        chars: pick.r.variants[pick.variant].chars, changes: pick.r.variants[pick.variant].changes,
        note: pick.r.approved_variant === pick.variant ? "approved" : null } : null;

  function copy() {
    if (!shown) return;
    const body = tab === "json" ? JSON.stringify(shown.json, null, 2) : shown.text;
    void navigator.clipboard?.writeText(body).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  }

  return (
    <div className="page">
      <div className="list">
        <div className="head">
          <h1>Prompts</h1>
          <div className="sub">The project's scripts — every saved version and every improved script — with each
            one's script journey (the structured breakdown the analysis judges against).</div>
        </div>
        {!lib && <p className="dimtxt">Loading…</p>}
        {lib && (
          <div className="lib">
            <div className="lib-list">
              <div className="jr-hd">Saved scripts</div>
              {lib.versions.map((v) => (
                <button key={v.version} className={pick?.kind === "version" && pick.v.version === v.version ? "on" : ""}
                  onClick={() => { setPick({ kind: "version", v }); setTab("text"); }}>
                  <b>v{v.version}</b>{v.active && <span className="pill good">active</span>}
                  <span className="dimtxt">{v.chars.toLocaleString()} chars · {v.journey_status}</span>
                </button>
              ))}
              {!lib.versions.length && <p className="dimtxt">No script yet — add one on the Projects page.</p>}
              <div className="jr-hd" style={{ marginTop: 14 }}>Improved scripts</div>
              {lib.improved.map((r) => (
                <div key={r.id} className="lib-run">
                  <div className="dimtxt">From v{r.base_version ?? "?"} · {new Date(r.created_at).toLocaleString()}
                    {r.status !== "ready" && ` · ${r.status}`}</div>
                  {Object.keys(r.variants).map((k) => (
                    <button key={k} className={pick?.kind === "improved" && pick.r.id === r.id && pick.variant === k ? "on" : ""}
                      onClick={() => { setPick({ kind: "improved", r, variant: k }); setTab("changes"); }}>
                      <b>{VARIANT[k] ?? k}</b>{r.approved_variant === k && <span className="pill good">approved</span>}
                      <span className="dimtxt">{r.variants[k].chars?.toLocaleString()} chars · {r.variants[k].changes.length} changes</span>
                    </button>
                  ))}
                </div>
              ))}
              {!lib.improved.length && <p className="dimtxt">None yet — they're built after an analysis finishes.</p>}
            </div>
            <div className="lib-view">
              {shown && (
                <>
                  <div className="lib-hd">
                    <b>{shown.title}</b> <span className="dimtxt">· {shown.chars?.toLocaleString()} chars{shown.note ? ` · ${shown.note}` : ""}</span>
                    <span style={{ marginLeft: "auto" }} />
                    {((shown.changes ? ["text", "json", "changes"] : ["text", "json"]) as ("text" | "json" | "changes")[]).map((t) => (
                      <button key={t} className={`lib-tab ${tab === t ? "on" : ""}`} onClick={() => setTab(t)}>
                        {t === "text" ? "Script" : t === "json" ? "Script journey (JSON)" : `Changes (${shown.changes?.length})`}
                      </button>
                    ))}
                    {tab !== "changes" && <button className="lib-tab" onClick={copy}>{copied ? "Copied" : "Copy"}</button>}
                  </div>
                  {tab === "text" && <pre className="lib-pre">{shown.text}</pre>}
                  {tab === "json" && <pre className="lib-pre">{shown.json ? JSON.stringify(shown.json, null, 2)
                    : "No script journey yet."}</pre>}
                  {tab === "changes" && shown.changes && (
                    <ul className="rsi-changes">
                      {shown.changes.map((c, i) => (
                        <li key={i}><b>{c.change}</b> {c.section} · {c.id}{c.at ? <span className="dimtxt"> · {c.at}</span> : null}
                          {c.reason && <div className="dimtxt">{c.reason}</div>}</li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </div>
          </div>
        )}
        <details className="lib-compare">
          <summary>Compare prompt versions by campaign</summary>
          <CampaignCompare />
        </details>
      </div>
    </div>
  );
}

function CampaignCompare() {
  const [campaignId, setCampaignId] = useState("");
  const [rows, setRows] = useState<PromptComparison[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setRows(await comparePrompts(campaignId.trim() || undefined));
    } catch (err) {
      setRows(null);
      setError(err instanceof Error ? err.message : "Could not load prompt versions");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
        <div className="sub">
          Each hash is one prompt version: the campaign script without that
          customer's name or the callback clock. Rates are among calls a person answered.
        </div>
        <form
          className="row"
          onSubmit={(event) => {
            event.preventDefault();
            void load();
          }}
        >
          <InputField
            label="Campaign"
            value={campaignId}
            onChange={(event) => setCampaignId(event.target.value)}
            placeholder="Campaign id"
          />
          <Button type="submit" disabled={loading}>
            {loading ? "Loading" : "Compare"}
          </Button>
        </form>
        {error && <p className="error">{error}</p>}
        {rows && rows.length === 0 && <p className="sub">No calls for that campaign yet.</p>}
        {rows && rows.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Calls</th>
                <th>Answered</th>
                <th>Objective</th>
                <th>Script</th>
                <th>Guardrails</th>
                <th>Voice to voice</th>
                <th>Avg cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.sha256 ?? "unversioned"}>
                  <td>
                    <div>{row.sha256 ? row.sha256.slice(0, 12) : "No version"}</div>
                    <div className="sub">{row.preview || "Prompt text was not registered."}</div>
                  </td>
                  <td>{row.calls}</td>
                  <td>{row.connected}</td>
                  <td>{rate(row.objective_rate)}</td>
                  <td>{rate(row.adherence_rate)}</td>
                  <td>{rate(row.guardrail_rate)}</td>
                  <td>{ms(row.v2v_p50_ms)}</td>
                  <td>{money(row.avg_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
    </div>
  );
}

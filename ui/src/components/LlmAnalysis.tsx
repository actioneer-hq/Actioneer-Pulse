import { useState } from "react";
import type { Judgment } from "../api";

const FIELDS: [keyof Judgment, string][] = [
  ["sentiment", "Sentiment"],
  ["objective_achieved", "Objective"],
  ["answered_by", "Answered by"],
  ["script_adherence", "Script adherence"],
  ["primary_language", "Language"],
  ["escalation_requested", "Escalation"],
  ["callback_requested", "Callback"],
  ["guardrail_violation", "Guardrail violation"],
];

const fmt = (v: unknown): string =>
  v == null || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v);

// Conditional fields only appear when their trigger is set (callback_time when a callback was
// requested; violation points when a guardrail was actually broken).
function rowsFor(j: Judgment): [keyof Judgment, string][] {
  const rows = [...FIELDS];
  if (j.callback_requested) rows.splice(7, 0, ["callback_time", "Callback time"]);
  return rows;
}

export default function LlmAnalysis({ judgment }: { judgment: Judgment | null }) {
  const [open, setOpen] = useState(false);
  // A judgment row exists but status "skipped" = connected-but-no-model, or not connected.
  const judged = judgment && judgment.status === "ok";

  return (
    <section className="sec">
      <h3 className="collapse" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chev open={open} />
        LLM analysis
        <span className="right">{judged ? (judgment!.model ?? "judged") : "not run"}</span>
      </h3>
      {open && (
        <div className="disclose">
          {!judged ? (
            <p className="dimtxt">
              No LLM judgment for this call. It runs when the org has a post-call-analysis model
              configured and the call connected.
            </p>
          ) : (
            <>
              <dl className="meta">
                {rowsFor(judgment!).map(([k, label]) => (
                  <div key={k}><dt>{label}</dt><dd>{fmt(judgment![k])}</dd></div>
                ))}
              </dl>
              {judgment!.guardrail_violation && judgment!.guardrail_violation_points?.length ? (
                <div className="violations">
                  <div className="violations-hd">Guardrails broken</div>
                  <ul>
                    {judgment!.guardrail_violation_points!.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
              ) : null}
              {judgment!.summary && <p className="fn">{judgment!.summary}</p>}
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Chev({ open }: { open: boolean }) {
  return (
    <svg className={`chev${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 24 24"
         fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
         strokeLinejoin="round" aria-hidden="true">
      <polyline points="9 6 15 12 9 18" />
    </svg>
  );
}

import { useState } from "react";
import type { Judgment } from "../api";

// [key, label, "what it means" tip] — tip shows on hover over the label.
const FIELDS: [keyof Judgment, string, string][] = [
  ["sentiment", "Sentiment", "Overall caller sentiment across the call, from very negative to very positive."],
  ["objective_achieved", "Objective", "Whether the call's goal was achieved, partially met, or not achieved."],
  ["answered_by", "Answered by", "Who or what picked up: a human, voicemail, an IVR, or unknown."],
  ["script_adherence", "Script adherence", "How closely the agent followed its configured script."],
  ["primary_language", "Language", "The main language spoken during the call."],
  ["escalation_requested", "Escalation", "Did the caller ask to be escalated to a human or supervisor."],
  ["callback_requested", "Callback", "Did the caller ask to be called back later."],
  ["guardrail_violation", "Guardrail violation", "Did the call break any of the agent's configured guardrails."],
];

const CALLBACK_TIME_TIP = "When the caller wants to be called back, if a time was stated.";

const fmt = (v: unknown): string =>
  v == null || v === "" ? "—" : typeof v === "boolean" ? (v ? "yes" : "no") : String(v);

// Conditional fields only appear when their trigger is set (callback_time when a callback was
// requested; violation points when a guardrail was actually broken).
function rowsFor(j: Judgment): [keyof Judgment, string, string][] {
  const rows = [...FIELDS];
  if (j.callback_requested) rows.splice(7, 0, ["callback_time", "Callback time", CALLBACK_TIME_TIP]);
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
                {rowsFor(judgment!).map(([k, label, tip]) => (
                  <div key={k}>
                    <dt><span className="tip" data-tip={tip}>{label}</span></dt>
                    <dd>{fmt(judgment![k])}</dd>
                  </div>
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

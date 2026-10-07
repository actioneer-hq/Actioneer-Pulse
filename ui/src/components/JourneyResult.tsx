import { useState } from "react";
import type { CallJourney, Cause } from "../api";

// How this call went against its script's journey: stages reached, what the customer did and whether
// the agent handled it (with the cause when it didn't), guardrails broken, unscripted moments, and every
// failure with the turns it happened at. The decision model's part shows at once; the LLM's part
// (summary, unscripted, turns) fills in when enrichment finishes. Short calls show one compact row.

const CAUSE_LABEL: Record<string, string> = {
  script_gap: "script gap",
  not_followed: "not followed",
};
const CAUSE_TIP: Record<string, string> = {
  script_gap: "The script has no instruction for this — fix the script.",
  not_followed: "The script covers it but the agent didn't do it — model / training data.",
};

function CauseChip({ cause }: { cause: Cause }) {
  if (!cause) return null;
  return <span className={`cause-chip ${cause}`} title={CAUSE_TIP[cause]}>{CAUSE_LABEL[cause]}</span>;
}

const pretty = (v: string | null | undefined) => (v ? v.replace(/_/g, " ") : "—");

const KIND: Record<string, string> = {
  stage: "missed stage", branch: "customer situation", guardrail: "guardrail", standard: "callback / human",
  opening: "opening", closing: "closing", unscripted: "not in script",
};

export default function JourneyResult({ journey, enrich }: { journey?: CallJourney | null; enrich?: string | null }) {
  const [open, setOpen] = useState(true);
  if (!journey) return null;
  const short = journey.format === "short";
  const furthest = journey.furthest_stage;
  const happened = journey.branches?.filter((b) => b.happened) ?? [];
  const analysing = enrich === "pending" || enrich === "running";

  return (
    <section className="sec">
      <h3 className="sec-toggle" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="chev">{open ? "▾" : "▸"}</span>
        Journey
        <span className="pill" style={{ marginLeft: 8 }}>{short ? "short call" : "full"}</span>
        <span className="right">{pretty(journey.objective_achieved)}</span>
      </h3>
      {open && (
        <div className="disclose">
          <dl className="meta">
            <div><dt>Answered by</dt><dd>{pretty(journey.answered_by)}</dd></div>
            <div><dt>Furthest stage</dt><dd>{furthest ?? "ended during the opening"}</dd></div>
            {journey.opening_done != null && <div><dt>Opening</dt><dd>{journey.opening_done ? "done" : "not done"}</dd></div>}
            {journey.closing_done != null && <div><dt>Closing</dt><dd>{journey.closing_done ? "done" : "not done"}</dd></div>}
            <div><dt>Language</dt>
              <dd>{journey.language?.primary ?? journey.primary_language ?? "—"}
                {journey.language?.secondary?.length ? ` (+ ${journey.language.secondary.join(", ")})` : ""}</dd></div>
            <div><dt>Sentiment</dt><dd>{pretty(journey.sentiment)}</dd></div>
            {!short && <div><dt>Ended by</dt><dd>{journey.ended_by ?? "—"}</dd></div>}
          </dl>

          {!short && journey.stages && (
            <div className="stage-strip">
              {journey.stages.map((s) => (
                <span key={s.stage} className={`stage ${s.reached ? "on" : ""}`}>{s.stage}</span>
              ))}
            </div>
          )}

          {happened.length > 0 && (
            <div className="jr-block">
              <div className="jr-hd">What the customer did</div>
              {happened.map((b, i) => (
                <div key={i} className="jr-row">
                  <span className={b.handled ? "ok" : "bad"}>{b.handled ? "✓" : "✗"}</span>
                  <div>
                    <div>{b.if}{b.stage ? <span className="dimtxt"> · {b.stage}</span> : null}
                      {" "}<CauseChip cause={b.cause} />
                      {b.in_script === false && <span className="cause-chip script_gap">not in script</span>}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {journey.guardrails_broken && journey.guardrails_broken.length > 0 && (
            <div className="jr-block">
              <div className="jr-hd">Guardrails broken</div>
              {journey.guardrails_broken.map((g, i) => (
                <div key={i} className="jr-row">
                  <span className="bad">✗</span>
                  <div>{g.rule} <CauseChip cause={g.cause} /></div>
                </div>
              ))}
            </div>
          )}

          {journey.standard && (journey.standard.callback_requested || journey.standard.escalation_requested) && (
            <div className="jr-block">
              <div className="jr-hd">Callback / human</div>
              {journey.standard.callback_requested && (
                <div className="jr-row">
                  <span className={journey.standard.callback_handled ? "ok" : "bad"}>
                    {journey.standard.callback_handled ? "✓" : "✗"}</span>
                  <div>Callback requested{journey.standard.callback_time ? ` — ${journey.standard.callback_time}` : ""}
                    {" "}<CauseChip cause={(journey.standard.callback_cause as Cause) ?? null} /></div>
                </div>
              )}
              {journey.standard.escalation_requested && (
                <div className="jr-row">
                  <span className={journey.standard.escalation_handled ? "ok" : "bad"}>
                    {journey.standard.escalation_handled ? "✓" : "✗"}</span>
                  <div>Asked for a human <CauseChip cause={(journey.standard.escalation_cause as Cause) ?? null} /></div>
                </div>
              )}
            </div>
          )}

          {journey.unscripted && journey.unscripted.length > 0 && (
            <div className="jr-block">
              <div className="jr-hd">Not covered by the script</div>
              {journey.unscripted.map((u, i) => (
                <div key={i} className="jr-row">
                  <span className={u.agent_response_ok ? "ok" : "bad"}>{u.agent_response_ok ? "✓" : "✗"}</span>
                  <div>turn {u.turn}: {u.what} <CauseChip cause="script_gap" /></div>
                </div>
              ))}
            </div>
          )}

          {journey.wrong_values && journey.wrong_values.length > 0 && (
            <div className="jr-block">
              <div className="jr-hd">Wrong values</div>
              {journey.wrong_values.map((w, i) => (
                <div key={i} className="jr-row"><span className="bad">✗</span>
                  <div>turn {w.turn}: {w.param} — said “{w.said}”, expected “{w.expected}”</div></div>
              ))}
            </div>
          )}

          {journey.failures && journey.failures.length > 0 && (
            <div className="jr-block">
              <div className="jr-hd">Failures{analysing ? " · finding turns…" : ""}</div>
              {journey.failures.map((f, i) => (
                <div key={i} className="jr-row">
                  <span className="bad">✗</span>
                  <div>{f.item} <span className="dimtxt">· {KIND[f.kind] ?? f.kind}</span>{" "}
                    <CauseChip cause={f.cause} />
                    {f.turns.length > 0 && <span className="dimtxt"> · turn {f.turns.join(", ")}</span>}</div>
                </div>
              ))}
            </div>
          )}

          {analysing && <p className="dimtxt">Summary and script gaps are being analysed…</p>}
          {enrich === "failed" && <p className="dimtxt">Couldn't analyse the summary and script gaps.</p>}
          {journey.summary && <p className="fn">{journey.summary}</p>}
        </div>
      )}
    </section>
  );
}

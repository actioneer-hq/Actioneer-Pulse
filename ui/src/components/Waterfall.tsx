import { useState } from "react";
import { STAGES, type Span, type Trace } from "../api";
import { dur } from "../format";

type Node = { span: Span; depth: number };

/** Depth-first, so a parent is always immediately above its children. */
function flatten(spans: Span[]): Node[] {
  const kids = new Map<string | null, Span[]>();
  for (const s of spans) {
    const list = kids.get(s.parent_span_id) ?? [];
    list.push(s);
    kids.set(s.parent_span_id, list);
  }
  const out: Node[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const span of kids.get(parent) ?? []) {
      out.push({ span, depth });
      walk(span.span_id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

export default function Waterfall({ trace }: { trace: Trace }) {
  const [open, setOpen] = useState(false);
  const total = Math.max(
    ...trace.spans.map((s) => s.t_start_s + (s.duration_s ?? 0)),
    0.001,
  );
  return (
    <section className="sec">
      <h3 className="sec-toggle" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg className={`chev${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
             strokeLinejoin="round" aria-hidden="true">
          <polyline points="9 6 15 12 9 18" />
        </svg>
        Trace <span className="right">{trace.spans.length} spans</span>
      </h3>
      {open && (
      <div className="disclose"><div className="legend">
        {STAGES.map((s) => (
          <span key={s}>
            <i className="dot" style={{ background: `var(--${s})` }} />
            {s}
          </span>
        ))}
      </div>
      <div className="wf">
        {flatten(trace.spans).map(({ span, depth }) => (
          <details key={span.span_id} className="sp">
            <summary>
              <div className="row">
                <div className="lbl" style={{ paddingLeft: depth * 14 }} title={span.name ?? ""}>
                  <i className="dot" style={{ background: `var(--${span.stage})` }} />
                  {span.name}
                </div>
                <div className="track">
                  <div
                    className="bar"
                    style={{
                      left: `${(100 * span.t_start_s) / total}%`,
                      width: `${(100 * (span.duration_s ?? 0)) / total}%`,
                      background: `var(--${span.stage})`,
                    }}
                  />
                  {span.events.map((e, i) => (
                    <div
                      key={i}
                      className="tick"
                      style={{ left: `${(100 * e.t_offset_s) / total}%` }}
                      title={`${e.name} @${e.t_offset_s.toFixed(2)}s${
                        e.content_text ? ` — ${e.content_text.slice(0, 80)}` : ""
                      }`}
                    />
                  ))}
                </div>
                <div className="dur">
                  {span.duration_s == null ? "open" : dur(span.duration_s * 1000)}
                </div>
              </div>
            </summary>
            <div className="panel">
              {span.content_text && <pre>{span.content_text}</pre>}
              <pre>{JSON.stringify(span.attrs, null, 1)}</pre>
              {span.events.length > 0 && (
                <pre>
                  {span.events
                    .map(
                      (e) =>
                        `${e.t_offset_s.toFixed(3)}s  ${e.name}` +
                        (e.content_text ? `  ${e.content_text.slice(0, 140)}` : ""),
                    )
                    .join("\n")}
                </pre>
              )}
            </div>
          </details>
        ))}
      </div></div>
      )}
    </section>
  );
}

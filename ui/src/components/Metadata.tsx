import type { ReactNode } from "react";
import type { CallDetail } from "../api";

const dash = (v: unknown): string => (v == null || v === "" ? "—" : String(v));

export default function Metadata({ data }: { data: CallDetail }) {
  const h = data.call;
  const t = data.trust;
  const cov = t.capture_coverage;
  const coverage: ReactNode = !t.audio_analysis ? (
    <span className="meta-off">
      Audio analysis off
      <em>required for coverage</em>
    </span>
  ) : Array.isArray(cov) ? (
    cov.map((x) => `${+(x * 100).toFixed(2)}%`).join(" / ")
  ) : Object.keys(cov).length ? (
    Object.entries(cov).map(([k, v]) => `${k} ${+((v as number) * 100).toFixed(2)}%`).join(" · ")
  ) : (
    "—"
  );
  const rows: [string, ReactNode][] = [
    ["Engine", dash(h.engine)],
    ["STT", dash(h.stt_provider)],
    ["LLM", dash(h.llm_provider)],
    ["TTS", dash(h.tts_provider)],
    ["Tokens in / out", `${dash(h.tokens_in)} / ${dash(h.tokens_out)}`],
    ["Cost", h.cost_total != null ? `${+h.cost_total.toFixed(6)} ${h.cost_currency ?? ""}` : "—"],
    ["Capture coverage", coverage],
    ["Dropped span events", dash(t.span_dropped_events)],
  ];
  return (
    <section className="sec">
      <h3>Metadata</h3>
      <dl className="meta">
        {rows.map(([k, v]) => (
          <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
        ))}
      </dl>
    </section>
  );
}

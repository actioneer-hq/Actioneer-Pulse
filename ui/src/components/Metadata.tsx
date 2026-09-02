import type { CallDetail } from "../api";

const dash = (v: unknown): string => (v == null || v === "" ? "—" : String(v));

export default function Metadata({ data }: { data: CallDetail }) {
  const h = data.call;
  const t = data.trust;
  const cov = t.capture_coverage;
  const coverage = Array.isArray(cov)
    ? cov.map((x) => `${Math.round(x * 100)}%`).join(" / ")
    : Object.keys(cov).length
      ? Object.entries(cov).map(([k, v]) => `${k} ${Math.round((v as number) * 100)}%`).join(" · ")
      : "—";
  const rows: [string, string][] = [
    ["Engine", dash(h.engine)],
    ["Carrier", dash(h.carrier)],
    ["STT", dash(h.stt_provider)],
    ["LLM", dash(h.llm_provider)],
    ["TTS", dash(h.tts_provider)],
    ["Voice", dash(h.voice)],
    ["Campaign", dash(h.campaign_id ?? h.labels.campaign_id)],
    ["Ended by", h.hangup_by ? `${h.hangup_by}${h.terminal_reason ? ` · ${h.terminal_reason}` : ""}` : "—"],
    ["Tokens in / out", `${dash(h.tokens_in)} / ${dash(h.tokens_out)}`],
    ["Cost", h.cost_total != null ? `${h.cost_total.toFixed(3)} ${h.cost_currency ?? ""}` : "—"],
    ["Capture coverage", coverage],
    ["Dropped span events", dash(t.span_dropped_events)],
    ["Unattributed spans", dash(t.unattributed_spans)],
    ["Versions", `metric ${dash(h.metric_version)} · adapter ${dash(h.adapter_version)} · app ${dash(h.app_version)}`],
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

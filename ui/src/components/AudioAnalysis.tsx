import { useState } from "react";
import type { CallDetail } from "../api";

// The Layer-1 audio metrics (computed from the waveform): [name, label, tip, formatter].
const AUDIO_METRICS: [string, string, string, (v: number) => string][] = [
  ["capture_coverage", "Capture coverage",
    "Fraction of the call that has real captured audio (not dropped frames or carrier silence).",
    (v) => `${(v * 100).toFixed(1)}%`],
  ["talk_ratio_caller", "Talk ratio · caller",
    "Share of the call's duration the caller was speaking.", (v) => `${(v * 100).toFixed(1)}%`],
  ["talk_ratio_agent", "Talk ratio · agent",
    "Share of the call's duration the agent was speaking.", (v) => `${(v * 100).toFixed(1)}%`],
  ["overlap_ratio", "Overlap",
    "Share of the call where caller and agent spoke at the same time.",
    (v) => `${(v * 100).toFixed(1)}%`],
  ["barge_in", "Barge-ins",
    "Times the caller started speaking while the agent was still talking.", (v) => String(v)],
  ["dead_air_s", "Dead air",
    "Total silence where neither side spoke, counting only gaps past the tolerance.",
    (v) => `${v.toFixed(1)}s`],
  ["turn_count_caller", "Caller utterances",
    "Number of distinct caller speech segments detected in the audio.", (v) => String(v)],
  ["turn_count_agent", "Agent turns",
    "Number of distinct agent speaking turns.", (v) => String(v)],
  ["peak_dbfs", "Peak level",
    "Loudest moment in the recording, in dBFS (0 = maximum; more negative = quieter).",
    (v) => `${v.toFixed(1)} dBFS`],
  ["rms_dbfs", "RMS level",
    "Average loudness across the recording, in dBFS.", (v) => `${v.toFixed(1)} dBFS`],
  ["clipping_ratio", "Clipping",
    "Share of samples pinned at maximum amplitude — a sign of distortion.",
    (v) => `${(v * 100).toFixed(2)}%`],
];

export default function AudioAnalysis({ data }: { data: CallDetail }) {
  const [open, setOpen] = useState(false);
  if (!data.trust.audio_analysis) return null;  // only when the audio overlay actually ran

  const by = new Map(data.metrics.map((m) => [m.name, m]));
  const rows = AUDIO_METRICS
    .map(([name, label, tip, fmt]) => {
      const m = by.get(name);
      return m && m.available && typeof m.value === "number"
        ? [label, tip, fmt(m.value)] as [string, string, string] : null;
    })
    .filter((r): r is [string, string, string] => r !== null);

  return (
    <section className="sec">
      <h3 className="sec-toggle" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg className={`chev${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
             strokeLinejoin="round" aria-hidden="true"><polyline points="9 6 15 12 9 18" /></svg>
        Audio analysis <span className="right">ground truth</span>
      </h3>
      {open && (
        <div className="disclose">
          {rows.length ? (
            <dl className="meta">
              {rows.map(([k, tip, v]) => (
                <div key={k}>
                  <dt><span className="tip" data-tip={tip}>{k}</span></dt><dd>{v}</dd>
                </div>
              ))}
            </dl>
          ) : <p className="dimtxt">No audio metrics available.</p>}
        </div>
      )}
    </section>
  );
}

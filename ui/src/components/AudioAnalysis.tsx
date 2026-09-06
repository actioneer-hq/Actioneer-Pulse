import { useState } from "react";
import type { CallDetail } from "../api";

// The Layer-1 audio metrics (computed from the waveform), with a human label + formatter.
const AUDIO_METRICS: [string, string, (v: number) => string][] = [
  ["capture_coverage", "Capture coverage", (v) => `${(v * 100).toFixed(1)}%`],
  ["talk_ratio_caller", "Talk ratio · caller", (v) => `${(v * 100).toFixed(1)}%`],
  ["talk_ratio_agent", "Talk ratio · agent", (v) => `${(v * 100).toFixed(1)}%`],
  ["overlap_ratio", "Overlap", (v) => `${(v * 100).toFixed(1)}%`],
  ["barge_in", "Barge-ins", (v) => String(v)],
  ["dead_air_s", "Dead air", (v) => `${v.toFixed(1)}s`],
  ["turn_count_caller", "Caller utterances", (v) => String(v)],
  ["turn_count_agent", "Agent turns", (v) => String(v)],
  ["peak_dbfs", "Peak level", (v) => `${v.toFixed(1)} dBFS`],
  ["rms_dbfs", "RMS level", (v) => `${v.toFixed(1)} dBFS`],
  ["clipping_ratio", "Clipping", (v) => `${(v * 100).toFixed(2)}%`],
];

export default function AudioAnalysis({ data }: { data: CallDetail }) {
  const [open, setOpen] = useState(false);
  if (!data.trust.audio_analysis) return null;  // only when the audio overlay actually ran

  const by = new Map(data.metrics.map((m) => [m.name, m]));
  const rows = AUDIO_METRICS
    .map(([name, label, fmt]) => {
      const m = by.get(name);
      return m && m.available && typeof m.value === "number"
        ? [label, fmt(m.value)] as [string, string] : null;
    })
    .filter((r): r is [string, string] => r !== null);

  return (
    <section className="sec">
      <h3 className="collapse" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg className={`chev${open ? " open" : ""}`} width="12" height="12" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
             strokeLinejoin="round" aria-hidden="true"><polyline points="9 6 15 12 9 18" /></svg>
        Audio analysis <span className="right">ground truth</span>
      </h3>
      {open && (
        <div className="disclose">
          {rows.length ? (
            <dl className="meta">
              {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
            </dl>
          ) : <p className="dimtxt">No audio metrics available.</p>}
        </div>
      )}
    </section>
  );
}

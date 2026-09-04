import { useState } from "react";
import type { Discrepancy } from "../api";

const label = (d: Discrepancy) =>
  d.dimension === "transcript"
    ? d.field.replace("_wer", "").replace("_", " ") + " transcript"
    : d.field.replace(/_/g, " ") + (d.turn_index != null ? ` · turn ${d.turn_index}` : "");

const fmtVal = (d: Discrepancy, v: string | null) => {
  if (v == null) return "—";
  if (d.dimension === "transcript") return v;               // text snippet
  return `${v} ms`;                                          // timing
};

export default function Discrepancies(
  { discrepancies, audioOn }: { discrepancies: Discrepancy[]; audioOn: boolean },
) {
  const [open, setOpen] = useState(false);
  // Audio overlay off → the check can't run; show the section disabled/greyed, not expandable.
  if (!audioOn) {
    return (
      <section className="sec">
        <h3 className="disabled">
          <Chev open={false} />
          Ground truth vs reported
          <span className="right">audio analysis off</span>
        </h3>
      </section>
    );
  }
  const n = discrepancies.length;
  return (
    <section className="sec">
      <h3 className="collapse" role="button" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Chev open={open} />
        Ground truth vs reported
        <span className={`right ${n ? "bad" : ""}`}>{n ? `${n} flagged` : "audio agrees"}</span>
      </h3>
      {open && (
        <div className="disclose">
          {n === 0 ? (
            <p className="dimtxt">Audio agrees with reported spans.</p>
          ) : (
            discrepancies.map((d, i) => (
              <div className="disc" key={i}>
                <div className="disc-hd">
                  <span className="disc-field">{label(d)}</span>
                  {d.delta != null && (
                    <span className="disc-delta">
                      Δ {d.dimension === "transcript" ? `${(d.delta * 100).toFixed(0)}% WER` : `${d.delta} ms`}
                    </span>
                  )}
                </div>
                <div className="disc-row">
                  <span className="disc-lbl">reported</span>
                  <span className="disc-rep">{fmtVal(d, d.reported)}</span>
                </div>
                <div className="disc-row">
                  <span className="disc-lbl">audio</span>
                  <span className="disc-mea">{fmtVal(d, d.measured)}</span>
                </div>
                {d.note && <div className="disc-note">{d.note}</div>}
              </div>
            ))
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

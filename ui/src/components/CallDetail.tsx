import { useEffect, useState } from "react";
import { getCall, type CallDetail as Detail, type Trace } from "../api";
import { secs, when } from "../format";
import AudioAnalysis from "./AudioAnalysis";
import CallChat from "./CallChat";
import Discrepancies from "./Discrepancies";
import Latency from "./Latency";
import LlmAnalysis from "./LlmAnalysis";
import Metadata from "./Metadata";
import Recording from "./Recording";
import Transcript from "./Transcript";
import Waterfall from "./Waterfall";

type Props = { id: string; onClose: () => void };

export default function CallDetail({ id, onClose }: Props) {
  const [data, setData] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    getCall(id)
      .then((call) => live && setData(call))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [id]);

  return (
    <aside className="insp">
      <div className="hd">
        <div>
          <div className="mono title">{id}</div>
          {data && <Header data={data} />}
        </div>
        <button className="x" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="body">
        {error && <p className="dimtxt pad">{error}</p>}
        {!data && !error && <p className="dimtxt pad">Loading…</p>}
        {data?.call.analysis_error && (
          <div className="analysis-error-banner">
            <b>Analysis failed</b>
            <span>{data.call.analysis_error}</span>
          </div>
        )}
        {data && <Sections data={data} />}
        {data && (
          <section className="sec">
            <h3>Chat</h3>
            <CallChat callId={id} />
          </section>
        )}
      </div>
    </aside>
  );
}

function Header({ data }: { data: Detail }) {
  const h = data.call;
  return (
    <>
      <div className="dimtxt">
        {h.source} · {h.engine ?? "?"} · {h.environment} · started {when(h.started_at)} · lasted {secs(h.duration_s)}
      </div>
      <div className="pills">
        {h.analysis_mode && h.analysis_mode !== "full" && <span className="pill">{h.analysis_mode}</span>}
        {h.status === "failed" && <span className="pill bad">analysis failed</span>}
        {h.status === "unsupported" && <span className="pill bad">unsupported</span>}
        {h.status !== "unsupported" && h.metric_version == null && <span className="pill warn">not analysed yet</span>}
        {!data.trust.media_ready && <span className="pill warn">no audio</span>}
        {!data.trust.spans_complete && <span className="pill bad">spans incomplete</span>}
        {(data.trust.reasons ?? []).map((r) => {
          const t = TRUST_REASONS[r];
          if (!t) return null; // audio_missing/trace_missing etc. already covered by the pills above
          return <span key={r} className={`pill ${t.cls}`} title={t.tip}>{t.label}</span>;
        })}
      </div>
    </>
  );
}

// Calculator trust reasons worth their own pill — the ones the booleans above don't cover.
// label = what happened; tip = what it means for the numbers.
const TRUST_REASONS: Record<string, { label: string; cls: string; tip: string }> = {
  turns_derived_from_events: {
    label: "turns derived", cls: "",
    tip: "No turn spans in the telemetry — turn structure and latencies were inferred from the event timeline (stt.final → tts.first_audio).",
  },
  timing_missing: {
    label: "no timing", cls: "warn",
    tip: "The source carried no clock at all — dialogue and analysis work, latency metrics are absent (not zero).",
  },
  telemetry_truncated: {
    label: "telemetry truncated", cls: "warn",
    tip: "The producer dropped span events mid-call; some evidence never arrived.",
  },
  gate_timeout: {
    label: "computed partial", cls: "warn",
    tip: "Analysis ran before all evidence arrived (gate timed out); a late piece will trigger re-analysis.",
  },
};

function Sections({ data }: { data: Detail }) {
  const h = data.call;
  const trace: Trace = { call_id: h.id, source: h.source, duration_s: h.duration_s, spans: data.spans };
  return (
    <>
      <Recording data={data} />
      <AudioAnalysis data={data} />
      <Transcript turns={data.turns} spans={data.spans} />
      <Latency turns={data.turns} mediaReady={data.trust.media_ready} />
      <Waterfall trace={trace} />
      <LlmAnalysis judgment={data.judgment} />
      <Discrepancies discrepancies={data.discrepancies} audioOn={data.trust.audio_analysis} />
      <Metadata data={data} />
    </>
  );
}

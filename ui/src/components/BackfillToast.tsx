import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBackfill } from "../BackfillProvider";

// Persistent top-right toast tracking the active backfill job. Collapses to a small pill
// on close; re-expands when the pill is clicked. On done it shows an in-app summary with a
// link to the Calls page Failed tab (never a browser notification).
export default function BackfillToast() {
  const { job, cancel, dismiss } = useBackfill();
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();

  // Re-expand whenever a fresh job starts.
  useEffect(() => { if (job) setCollapsed(false); }, [job?.id]);

  if (!job) return null;

  const done = job.status === "done";
  const failed = job.status === "failed";
  const cancelled = job.status === "cancelled";
  const settled = done || failed || cancelled;
  const total = job.total || 0;
  const pctDone = total > 0 ? Math.min(100, Math.round((job.completed / total) * 100)) : 0;

  if (collapsed) {
    return (
      <button className="backfill-pill" onClick={() => setCollapsed(false)}>
        {!settled && <span className="chat-streaming" />}
        Backfill {settled ? job.status : `${job.completed}/${total || "?"}`}
      </button>
    );
  }

  const goFailed = () => {
    navigate("/calls?tab=failed");
    dismiss();
  };

  return (
    <div className="backfill-toast">
      <div className="backfill-toast-hd">
        {!settled && <span className="chat-streaming" />}
        <b>{settled ? "Backfill" : "Backfilling…"}</b>
        <span className="phase">{settled ? job.status : (job.phase ?? job.status)}</span>
        <button className="x" aria-label="Collapse" onClick={() => setCollapsed(true)}>×</button>
      </div>

      {!settled && (
        <>
          <div className="backfill-bar">
            <span style={{ width: `${pctDone}%` }} />
          </div>
          <div className="backfill-meta">
            <span>{job.completed}/{total || "?"} analyzed</span>
            {job.failed > 0 && <span className="bad">{job.failed} failed</span>}
          </div>
          <div className="backfill-foot">
            <button className="link bad" onClick={() => void cancel()}>Cancel</button>
          </div>
        </>
      )}

      {done && (
        <div className="backfill-summary">
          <div>{job.completed} analyzed, {job.failed} failed</div>
          {job.failed > 0 && (
            <button className="link" onClick={goFailed}>See Failed →</button>
          )}
          <button className="link" onClick={dismiss}>Dismiss</button>
        </div>
      )}

      {(failed || cancelled) && (
        <div className="backfill-summary">
          {failed && <div className="bad">{job.error ?? "Backfill failed"}</div>}
          {cancelled && <div className="dimtxt">Cancelled — {job.completed} analyzed.</div>}
          <button className="link" onClick={dismiss}>Dismiss</button>
        </div>
      )}
    </div>
  );
}

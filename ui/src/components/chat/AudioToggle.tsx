import { useState } from "react";
import { patchConversation } from "../../api";

// A small per-chat toggle for audio-native analysis. `cid` is the conversation id (from the
// loaded conversation / per-call chat payload). When unavailable, enabling is blocked and an
// inline warning is shown instead; the toggle stays off. Optimistic + persisted via PATCH.
export function AudioToggle(
  { cid, enabled, available, onChange }:
  { cid: string | null; enabled: boolean; available: boolean; onChange: (v: boolean) => void },
) {
  const [warn, setWarn] = useState(false);

  function click() {
    if (!cid) return;
    const next = !enabled;
    if (next && !available) { setWarn(true); return; }  // opt-in blocked while unavailable
    setWarn(false);
    onChange(next);                                       // optimistic
    patchConversation(cid, { audio_native_enabled: next })
      .then((r) => onChange(r.audio_native_enabled))      // reconcile with server
      .catch(() => onChange(!next));                      // roll back on failure
  }

  return (
    <div className="audio-toggle-wrap">
      <button type="button"
        className={`pill audio-toggle ${enabled ? "on" : ""}`}
        aria-pressed={enabled} disabled={!cid}
        title="Let the agent analyse call audio directly"
        onClick={click}>
        🔊 Audio analysis
      </button>
      {warn && (
        <div className="auth-error audio-warn">
          ⚠️ No audio-native model was configured at build time. Provide one
          (VOICEOBS_AUDIO_NATIVE_API_KEY) and restart the app to use audio analysis.
          <button className="audio-warn-x" onClick={() => setWarn(false)} aria-label="Dismiss">×</button>
        </div>
      )}
    </div>
  );
}

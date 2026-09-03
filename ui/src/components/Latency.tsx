import type { Turn } from "../api";
import { ms, pct } from "../format";

// [label, one-line "what it measures"] — the tip shows on header hover.
const COLS: [string, string][] = [
  ["Turn", "Turn number. Tags mark opening / interrupted turns."],
  ["Voice-to-voice", "Total gap the caller felt: they stop talking → first agent audio."],
  ["Endpoint", "Silence hold — waiting to be sure the caller finished."],
  ["STT", "Speech → text transcription time."],
  ["Think", "LLM time to first token."],
  ["Assembly", "First token → TTS node opens (~0 for streaming pipelines)."],
  ["Dispatch", "First token → TTS provider request fires (the real handoff)."],
  ["TTS", "Text → first speech byte (TTS warmup)."],
  ["Unattr.", "Leftover: voice-to-voice minus the pieces above."],
];

/** Voice-to-voice is the headline; the columns to its right are the span-derived
 *  pieces that add up to it. Opening and interrupted turns have no clean caller
 *  end-of-speech, so they are shown but kept out of the percentiles. */
export default function Latency({ turns, mediaReady }: { turns: Turn[]; mediaReady: boolean }) {
  const measurable = turns.filter((t) => t.trigger !== "opening" && !t.interrupted);
  const v2v = measurable.map((t) => t.response_latency_ms);
  const tiles: [string, string][] = [
    ["Median v2v", ms(pct(v2v, 0.5))],
    ["p90", ms(pct(v2v, 0.9))],
    ["Max", ms(pct(v2v, 1))],
  ];
  return (
    <section className="sec">
      <h3>Latency</h3>
      <div className="grid g3">
        {tiles.map(([l, v]) => (
          <div key={l}><span>{l}</span><b>{v}</b></div>
        ))}
      </div>
      <div className="latwrap"><table className="lat">
        <thead>
          <tr>{COLS.map(([label, tip], i) => (
            <th key={label} className={i ? "r" : undefined}>
              <span className="tip" data-tip={tip}>{label}</span>
            </th>
          ))}</tr>
        </thead>
        <tbody>
          {turns.map((t) => {
            const excluded = t.trigger === "opening" || t.interrupted;
            return (
              <tr key={t.turn_index}>
                <td>
                  {t.turn_index}
                  {t.trigger === "opening" && <span className="tag">opening</span>}
                  {t.interrupted && <span className="tag">interrupted</span>}
                  {t.abandoned && <span className="tag">abandoned</span>}
                </td>
                <td className={excluded ? "r dimtxt" : "r strong"}>{ms(t.response_latency_ms)}</td>
                <td className="r dimtxt">{ms(t.endpointing_ms)}</td>
                <td className="r dimtxt">{ms(t.stt_lag_ms)}</td>
                <td className="r dimtxt">{ms(t.llm_ttft_ms)}</td>
                <td className="r dimtxt">{ms(t.assembly_ms)}</td>
                <td className="r dimtxt">{ms(t.dispatch_ms)}</td>
                <td className="r dimtxt">{ms(t.tts_ttfb_ms)}</td>
                <td className="r dimtxt">{ms(t.unattributed_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table></div>
      <p className="fn">
        Voice-to-voice runs from the caller&apos;s end of speech to the first agent audio the engine
        sent. End of speech comes {mediaReady ? "from the waveform" : "from the STT final, since no audio has arrived"}.
        The other columns are component durations from spans; in a streaming pipeline they overlap
        (the LLM still emits while TTS speaks), so they need not sum to voice-to-voice. Unattr. is
        the wall-clock inside the window that no span covered — the genuinely unexplained gap.
        Opening and interrupted turns are shown but left out of the percentiles.
      </p>
    </section>
  );
}

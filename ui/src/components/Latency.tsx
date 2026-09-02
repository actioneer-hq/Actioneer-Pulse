import type { Turn } from "../api";
import { ms, pct } from "../format";

const COLS = ["Turn", "Voice-to-voice", "Endpoint", "STT", "Think", "Assembly", "TTS", "Unattr."];

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
    ["Measured", `${v2v.filter((x) => x != null).length}/${turns.length}`],
  ];
  return (
    <section className="sec">
      <h3>Latency</h3>
      <div className="grid g4">
        {tiles.map(([l, v]) => (
          <div key={l}><span>{l}</span><b>{v}</b></div>
        ))}
      </div>
      <div className="latwrap"><table className="lat">
        <thead>
          <tr>{COLS.map((c, i) => <th key={c} className={i ? "r" : undefined}>{c}</th>)}</tr>
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
                <td className="r dimtxt">{ms(t.tts_ttfb_ms)}</td>
                <td className="r dimtxt">{ms(t.unattributed_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table></div>
      <p className="fn">
        Voice-to-voice runs from the caller&apos;s end of speech to the first agent audio the engine
        sent. End of speech comes {mediaReady ? "from the waveform" : "from the STT final, since no audio has arrived"};
        the other columns come from spans and add up to it, minus what is unattributed.
        Opening and interrupted turns are shown but left out of the percentiles.
      </p>
    </section>
  );
}

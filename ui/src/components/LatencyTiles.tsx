import type { Turn } from "../api";
import { ms, pct } from "../format";

export default function LatencyTiles({ turns }: { turns: Turn[] }) {
  // "Think" not "voice-to-voice": the latter is measured from the waveform, and audio
  // is not wired up yet. Naming it honestly beats showing a number that means less.
  const think = turns.map((t) => t.llm_ttft_ms);
  const tiles: [string, string][] = [
    ["Median think", ms(pct(think, 0.5))],
    ["p90 think", ms(pct(think, 0.9))],
    ["Max think", ms(pct(think, 1))],
    ["Turns", String(turns.length)],
    ["Tokens in", String(turns.reduce((a, t) => a + (t.tokens_in ?? 0), 0))],
  ];
  return (
    <section>
      <h2>Latency</h2>
      <div className="tiles">
        {tiles.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <b>{value}</b>
          </div>
        ))}
      </div>
    </section>
  );
}

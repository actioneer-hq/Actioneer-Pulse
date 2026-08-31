import type { Turn } from "../api";
import { ms } from "../format";

const COLS = ["Turn", "Endpointing", "STT", "Think", "TTS TTFB", "Tokens", "Lang"];

export default function TurnTable({ turns }: { turns: Turn[] }) {
  return (
    <section>
      <h2>Turns</h2>
      <table className="grid">
        <thead>
          <tr>
            {COLS.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {turns.map((t) => (
            <tr key={t.turn_index}>
              <td>
                {t.turn_index}
                {t.interrupted && <span className="pill warn">interrupted</span>}
                {t.abandoned && <span className="pill bad">abandoned</span>}
                <div className="sub">{t.trigger}</div>
              </td>
              <td>{ms(t.endpointing_ms)}</td>
              <td>{ms(t.stt_lag_ms)}</td>
              <td>{ms(t.llm_ttft_ms)}</td>
              <td>{ms(t.tts_ttfb_ms)}</td>
              <td>
                {t.tokens_in ?? "—"} / {t.tokens_out ?? "—"}
              </td>
              <td>{t.language ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

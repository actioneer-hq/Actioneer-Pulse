import type { Span, Turn } from "../api";

type Line = { key: string; who: string; t: number | null; text: string; kind: "caller" | "agent" | "ghost" };

const LOST = /overheard|dropped|carried|promoted/;

/** Caller and agent turns as bubbles, with "heard but not used" STT fragments
 *  interleaved by time as dashed ghosts. Jaeger cannot show you the ghosts; they
 *  are the reason a voice-shaped viewer is worth building. */
export default function Transcript({ turns, spans }: { turns: Turn[]; spans: Span[] }) {
  const lines: Line[] = [];
  for (const t of turns) {
    const callerT = t.caller_utt_end_s ?? t.committed_at ?? t.stt_final_at;
    if (t.caller_transcript)
      lines.push({
        key: `c${t.turn_index}`, who: `caller · turn ${t.turn_index}`, kind: "caller",
        t: callerT, text: t.caller_transcript,
      });
    const said = t.llm_spoken ?? t.llm_raw;
    // Producers differ in which agent anchor they emit; fall back down the chain and,
    // failing all, sit just after the caller so the pair never splits.
    const agentT = t.agent_utt_start_s ?? t.tts_first_audio_at ?? t.tts_start_at
      ?? t.llm_first_token_at ?? (callerT != null ? callerT + 0.001 : null);
    if (said)
      lines.push({
        key: `a${t.turn_index}`, kind: "agent",
        who: `agent · turn ${t.turn_index}${t.cut_reason ? ` · cut by ${t.cut_reason.replace("_", "-")}` : ""}`,
        t: agentT, text: said,
      });
  }
  const ghosts = spans
    .flatMap((s) => s.events)
    .filter((e) => e.name && LOST.test(e.name) && e.content_text)
    .map((e, i) => ({
      key: `g${i}`, kind: "ghost" as const, t: e.t_offset_s,
      who: `heard but not used · ${e.name}`, text: e.content_text!,
    }));
  // Stable sort by time; lines with no timestamp keep turn order at the end.
  const all = [...lines, ...ghosts].sort((a, b) => (a.t ?? Infinity) - (b.t ?? Infinity));

  return (
    <section className="sec">
      <h3>
        Transcript
        <span className="right">{turns.length} turns · {ghosts.length} discarded</span>
      </h3>
      {all.length ? (
        all.map((l) => (
          <div key={l.key} className={`msg ${l.kind}`}>
            <div className="who">
              {l.t != null && <span>{l.t.toFixed(1)}s</span>}
              <span>{l.who}</span>
            </div>
            <div className="body">{l.text}</div>
          </div>
        ))
      ) : (
        <p className="dimtxt">No transcript on this call.</p>
      )}
    </section>
  );
}

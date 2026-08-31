import type { Turn } from "../api";

export default function Transcript({ turns }: { turns: Turn[] }) {
  const lines = turns.flatMap((t) => {
    const out: { who: string; text: string; caller: boolean; key: string }[] = [];
    if (t.caller_transcript)
      out.push({
        who: `Caller · turn ${t.turn_index}`,
        text: t.caller_transcript,
        caller: true,
        key: `c${t.turn_index}`,
      });
    const said = t.llm_spoken ?? t.llm_raw;
    if (said)
      out.push({
        who: `Agent · turn ${t.turn_index}`,
        text: said,
        caller: false,
        key: `a${t.turn_index}`,
      });
    return out;
  });

  return (
    <section>
      <h2>Transcript</h2>
      {lines.length ? (
        lines.map((l) => (
          <div key={l.key} className={`msg${l.caller ? " caller" : ""}`}>
            <div className="who">{l.who}</div>
            <div className="body">{l.text}</div>
          </div>
        ))
      ) : (
        <p className="sub">No transcript on this call.</p>
      )}
    </section>
  );
}

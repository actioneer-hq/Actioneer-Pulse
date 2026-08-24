import type { Trace } from "../api";

const LOST = /overheard|dropped|carried|promoted/;

/** Words the producer heard and no turn ever claimed. Jaeger cannot show you this;
 *  it is the whole reason a voice-shaped trace viewer is worth building. */
export default function Discarded({ trace }: { trace: Trace }) {
  const lost = trace.spans
    .flatMap((s) => s.events)
    .filter((e) => e.name && LOST.test(e.name) && e.content_text)
    .sort((a, b) => a.t_offset_s - b.t_offset_s);

  return (
    <section>
      <h2>Heard but not used ({lost.length})</h2>
      {lost.length ? (
        lost.map((e, i) => (
          <div key={i} className="msg ghost">
            <div className="who">
              {e.name} · {e.t_offset_s.toFixed(2)}s
            </div>
            <div className="body">{e.content_text}</div>
          </div>
        ))
      ) : (
        <p className="sub">Nothing discarded.</p>
      )}
    </section>
  );
}

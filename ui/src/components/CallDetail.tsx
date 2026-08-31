import { useEffect, useState } from "react";
import { getCall, type CallDetail as Detail, type Trace } from "../api";
import { secs } from "../format";
import Discarded from "./Discarded";
import LatencyTiles from "./LatencyTiles";
import Transcript from "./Transcript";
import TurnTable from "./TurnTable";
import Waterfall from "./Waterfall";

export default function CallDetail({ id }: { id: string }) {
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

  if (error) return <div className="pane empty">{error}</div>;
  if (!data) return <div className="pane empty">Loading…</div>;

  const h = data.call;
  const trace: Trace = { call_id: h.id, source: h.source, duration_s: h.duration_s, spans: data.spans };
  return (
    <main className="pane">
      <header>
        <h1 className="mono">{h.id}</h1>
        <div className="sub">
          {h.status} · {secs(h.duration_s)} · {h.engine ?? "?"} → {h.llm_provider ?? "?"} /{" "}
          {h.tts_provider ?? "?"} · {h.environment}
          {data.trust.media_ready ? "" : " · no audio"}
        </div>
      </header>
      <LatencyTiles turns={data.turns} />
      <TurnTable turns={data.turns} />
      <Transcript turns={data.turns} />
      <Discarded trace={trace} />
      <Waterfall trace={trace} />
    </main>
  );
}

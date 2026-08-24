import { useEffect, useState } from "react";
import { getCall, getTrace, type CallDetail as Detail, type Trace } from "../api";
import { secs } from "../format";
import Discarded from "./Discarded";
import LatencyTiles from "./LatencyTiles";
import Transcript from "./Transcript";
import TurnTable from "./TurnTable";
import Waterfall from "./Waterfall";

export default function CallDetail({ id }: { id: string }) {
  const [data, setData] = useState<{ call: Detail; trace: Trace } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    Promise.all([getCall(id), getTrace(id)])
      .then(([call, trace]) => live && setData({ call, trace }))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [id]);

  if (error) return <div className="pane empty">{error}</div>;
  if (!data) return <div className="pane empty">Loading…</div>;

  const h = data.call.call;
  return (
    <main className="pane">
      <header>
        <h1 className="mono">{h.id}</h1>
        <div className="sub">
          {h.status} · {secs(h.duration_s)} · {h.engine ?? "?"} → {h.llm_provider ?? "?"} /{" "}
          {h.tts_provider ?? "?"} · {h.environment}
          {data.call.trust.media_ready ? "" : " · no audio"}
        </div>
      </header>
      <LatencyTiles turns={data.call.turns} />
      <TurnTable turns={data.call.turns} />
      <Transcript turns={data.call.turns} />
      <Discarded trace={data.trace} />
      <Waterfall trace={data.trace} />
    </main>
  );
}

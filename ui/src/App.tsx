import { useEffect, useState } from "react";
import { listCalls, type Call } from "./api";
import CallDetail from "./components/CallDetail";
import CallList from "./components/CallList";

export default function App() {
  const [calls, setCalls] = useState<Call[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listCalls()
      .then((items) => {
        setCalls(items);
        setSelected((s) => s ?? items[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="app">
      <CallList calls={calls} selected={selected} onSelect={setSelected} error={error} />
      {selected ? <CallDetail id={selected} /> : <div className="pane empty">Pick a call</div>}
    </div>
  );
}

import { secs, when } from "../format";
import type { Call } from "../api";

type Props = {
  calls: Call[];
  selected: string | null;
  onSelect: (id: string) => void;
  error: string | null;
};

export default function CallList({ calls, selected, onSelect, error }: Props) {
  return (
    <aside className="list">
      <header>
        <h1>Calls</h1>
        <span className="sub">{error ?? `${calls.length} total`}</span>
      </header>
      <table>
        <tbody>
          {calls.map((c) => (
            <tr
              key={c.id}
              className={c.id === selected ? "on" : undefined}
              onClick={() => onSelect(c.id)}
            >
              <td>
                <div className="mono">{c.id}</div>
                <div className="sub">
                  {c.source} · {c.environment}
                  {c.labels.tenant_id ? ` · ${c.labels.tenant_id}` : ""}
                </div>
              </td>
              <td>
                <span
                  className={`pill ${
                    c.status === "unsupported" ? "bad" : c.turns ? "ok" : "warn"
                  }`}
                >
                  {c.status}
                </span>
              </td>
              <td className="right">
                {secs(c.duration_s)}
                <div className="sub">{c.turns} turns</div>
              </td>
              <td className="right sub">{when(c.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!calls.length && !error && <p className="sub pad">Nothing ingested yet.</p>}
    </aside>
  );
}

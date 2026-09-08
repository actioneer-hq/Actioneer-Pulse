import type { Call } from "../api";
import { ms, secs, when } from "../format";

type Props = {
  calls: Call[];
  selected: string | null;
  onSelect: (id: string) => void;
};

export default function CallTable({ calls, selected, onSelect }: Props) {
  return (
    <div className="scroll">
      <table>
        <thead>
          <tr>
            <th>Call</th>
            <th className="r">p50 v2v</th>
            <th className="r">Turns</th>
            <th className="r">Duration</th>
            <th className="r">Started</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr
              key={c.id}
              className={c.id === selected ? "on" : undefined}
              tabIndex={0}
              onClick={() => onSelect(c.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(c.id)}
            >
              <td>
                <div className="mono">
                  {c.id}
                  {c.analysis_mode && c.analysis_mode !== "full" && (
                    <span className="pill" style={{ marginLeft: 6 }}>{c.analysis_mode}</span>
                  )}
                  {c.status === "failed" && (
                    <span className="pill bad" style={{ marginLeft: 6 }}>failed</span>
                  )}
                </div>
                <div className="dimtxt">
                  {c.source} · {c.environment}
                  {c.labels.campaign_id ? ` · ${c.labels.campaign_id}` : ""}
                  {c.status === "unsupported" ? " · unsupported" : c.status === "failed" ? " · analysis failed" : !c.analysed ? " · not analysed yet" : !c.media_ready ? " · no audio" : ""}
                </div>
              </td>
              <td className="r">{ms(c.p50_v2v_ms)}</td>
              <td className="r">{c.turns}</td>
              <td className="r">{secs(c.duration_s)}</td>
              <td className="r dimtxt">{when(c.started_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!calls.length && <p className="dimtxt pad">Nothing to show.</p>}
    </div>
  );
}

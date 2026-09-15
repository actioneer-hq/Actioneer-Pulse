import { Badge, Table, TableBody, TableCell, TableColumn, TableHeader, TableRow } from "@actioneer/ads";
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
      <Table>
        <TableHeader>
          <TableRow>
            <TableColumn>Call</TableColumn>
            <TableColumn className="r">p50 v2v</TableColumn>
            <TableColumn className="r">Turns</TableColumn>
            <TableColumn className="r">Duration</TableColumn>
            <TableColumn className="r">Started</TableColumn>
          </TableRow>
        </TableHeader>
        <TableBody>
          {calls.map((c) => (
            <TableRow
              key={c.id}
              data-selected={c.id === selected || undefined}
              tabIndex={0}
              onClick={() => onSelect(c.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(c.id)}
            >
              <TableCell>
                <div className="mono">
                  {c.id}
                  {c.analysis_mode && c.analysis_mode !== "full" && (
                    <Badge variant="soft" style={{ marginLeft: 6 }}>{c.analysis_mode}</Badge>
                  )}
                  {c.status === "failed" && (
                    <Badge variant="soft" color="danger" style={{ marginLeft: 6 }}>failed</Badge>
                  )}
                </div>
                <div className="dimtxt">
                  {c.source} · {c.environment}
                  {c.labels.campaign_id ? ` · ${c.labels.campaign_id}` : ""}
                  {c.status === "unsupported" ? " · unsupported" : c.status === "failed" ? " · analysis failed" : !c.analysed ? " · not analysed yet" : !c.media_ready ? " · no audio" : ""}
                </div>
              </TableCell>
              <TableCell className="r">{ms(c.p50_v2v_ms)}</TableCell>
              <TableCell className="r">{c.turns}</TableCell>
              <TableCell className="r">{secs(c.duration_s)}</TableCell>
              <TableCell className="r dimtxt">{when(c.started_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {!calls.length && <p className="dimtxt pad">Nothing to show.</p>}
    </div>
  );
}

import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import type { ClusterView } from "../../api";

export const CHART_COLORS = [
  "var(--chart-1)", "var(--chart-2)", "var(--chart-3)",
  "var(--chart-4)", "var(--chart-5)", "var(--chart-6)",
];

export type Row = Record<string, string | number | null>;
export type SeriesDef = { key: string; label: string; color: string };

const AXIS = { stroke: "var(--dim)", fontSize: 11 };
const GRID = "var(--chart-grid)";

const tooltipStyle = {
  background: "var(--ink)", border: "none", borderRadius: 4,
  color: "var(--panel)", fontSize: 12, padding: "6px 9px",
};
// Recharts colors item/label text by series color by default — force light text on the dark box.
const tipText = { color: "var(--panel)" };
const TIP = { contentStyle: tooltipStyle, itemStyle: tipText, labelStyle: tipText } as const;

function Card({ title, right, children }: {
  title: string; right?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="panel-card board-card">
      <h3>{title}{right && <span className="right">{right}</span>}</h3>
      <div className="board-chart">
        <ResponsiveContainer width="100%" height={200}>{children as never}</ResponsiveContainer>
      </div>
    </div>
  );
}

export function LineCard({ title, right, data, series, xKey = "t", fmtY }: {
  title: string; right?: React.ReactNode; data: Row[]; series: SeriesDef[];
  xKey?: string; fmtY?: (v: number) => string;
}) {
  return (
    <Card title={title} right={right}>
      <LineChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={28} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44}
          tickFormatter={fmtY ? (v) => fmtY(Number(v)) : undefined} />
        <Tooltip {...TIP} formatter={fmtY ? (v) => fmtY(Number(v)) : undefined} />
        {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 11 }} />}
        {series.map((s) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color}
            strokeWidth={2} dot={{ r: 2, fill: s.color, strokeWidth: 0 }}
            activeDot={{ r: 4 }} connectNulls />
        ))}
      </LineChart>
    </Card>
  );
}

export function AreaCard({ title, right, data, series, xKey = "t", fmtY }: {
  title: string; right?: React.ReactNode; data: Row[]; series: SeriesDef[];
  xKey?: string; fmtY?: (v: number) => string;
}) {
  return (
    <Card title={title} right={right}>
      <AreaChart data={data} margin={{ top: 6, right: 12, bottom: 0, left: -8 }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.key} id={`g-${s.key}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey={xKey} tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }} minTickGap={28} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44}
          tickFormatter={fmtY ? (v) => fmtY(Number(v)) : undefined} />
        <Tooltip {...TIP} formatter={fmtY ? (v) => fmtY(Number(v)) : undefined} />
        {series.map((s) => (
          <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color}
            strokeWidth={2} fill={`url(#g-${s.key})`} dot={{ r: 2, fill: s.color, strokeWidth: 0 }}
            activeDot={{ r: 4 }} connectNulls />
        ))}
      </AreaChart>
    </Card>
  );
}

const clusterColor = (k: number | null) =>
  k == null ? "var(--chart-6)" : `var(--chart-${(k % 6) + 1})`;

// 2D scatter of one lever's clusters: points coloured by cluster, hover shows the theme label.
export function ScatterCard({ title, view, onSelect }: {
  title: string; view: ClusterView; onSelect?: (callId: string) => void;
}) {
  const labelOf = new Map(view.clusters.map((c) => [c.key, c.label]));
  const groups = new Map<number | null, ClusterView["points"]>();
  for (const p of view.points) {
    if (!groups.has(p.cluster_key)) groups.set(p.cluster_key, []);
    groups.get(p.cluster_key)!.push(p);
  }
  const right = `${view.clusters.length} clusters · ${view.points.length} calls`;
  const tip = ({ active, payload }: { active?: boolean; payload?: { name?: string; payload?: { call_id?: string } }[] }) =>
    active && payload?.length ? (
      <div style={{ ...tooltipStyle }}>
        <div>{payload[0].name}</div>
        <div style={{ color: "var(--dim)", fontSize: 11 }}>{payload[0].payload?.call_id}</div>
      </div>
    ) : null;
  return (
    <Card title={title} right={right}>
      <ScatterChart margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis type="number" dataKey="x" hide />
        <YAxis type="number" dataKey="y" hide />
        <ZAxis range={[26, 26]} />
        <Tooltip content={tip} cursor={{ strokeDasharray: "3 3" }} />
        {[...groups.entries()].map(([k, pts]) => (
          <Scatter key={String(k)} data={pts} fill={clusterColor(k)}
            name={k == null ? "unclustered" : (labelOf.get(k) ?? `Cluster ${k}`)}
            onClick={(p: { call_id?: string }) => p.call_id && onSelect?.(p.call_id)} />
        ))}
      </ScatterChart>
    </Card>
  );
}

export function DonutCard({ title, data }: {
  title: string; data: { name: string; value: number; color: string }[];
}) {
  const total = data.reduce((a, d) => a + d.value, 0);
  return (
    <Card title={title}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={48} outerRadius={78}
          paddingAngle={2} stroke="var(--panel)">
          {data.map((d) => <Cell key={d.name} fill={d.color} />)}
        </Pie>
        <Tooltip {...TIP}
          formatter={(v: number, n) => [`${v} (${total ? Math.round((v / total) * 100) : 0}%)`, n]} />
        <Legend iconType="circle" wrapperStyle={{ fontSize: 11 }} />
      </PieChart>
    </Card>
  );
}

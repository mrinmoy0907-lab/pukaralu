import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ComposedChart, Tooltip, XAxis, YAxis } from "recharts";
import type { Observation } from "../types";

const PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#8c564b", "#17becf", "#e377c2"];

export interface SeriesSpec {
  key: string;
  label: string;
  values: number[];
  times?: number[];
  dashed?: boolean;
}

/** Merge several series (possibly with different time bases) into recharts rows. */
export function toRows(series: SeriesSpec[], baseTimes: number[], maxPoints = 400) {
  const step = Math.max(1, Math.ceil(baseTimes.length / maxPoints));
  const rows: Record<string, number>[] = [];
  for (let i = 0; i < baseTimes.length; i += step) {
    const t = baseTimes[i];
    const row: Record<string, number> = { t };
    for (const s of series) {
      if (!s.times) row[s.key] = s.values[i];
      else {
        // nearest earlier sample of a series with its own time base
        let j = 0;
        while (j + 1 < s.times.length && s.times[j + 1] <= t) j++;
        row[s.key] = s.values[j];
      }
    }
    rows.push(row);
  }
  return rows;
}

export function TimeChart({ title, unit, series, times, now, limit, observations, height = 170 }: {
  title: string;
  unit: string;
  series: SeriesSpec[];
  times: number[];
  now?: number;
  limit?: { value: number; label: string };
  observations?: Observation[];
  height?: number;
}) {
  const rows = toRows(series, times);
  const obs = (observations ?? []).filter((o) => o.t_offset_s !== null).map((o) => ({ t: o.t_offset_s!, obs: o.count, kind: o.kind }));
  return (
    <div className="chart">
      <div className="chart-title">
        {title} <span className="muted small">({unit}, simulated{obs.length ? "; dots = observed/forecast" : ""})</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={rows} margin={{ top: 4, right: 12, bottom: 0, left: -8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334" />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10 }} tickFormatter={(v) => `${Math.round(v / 60)}m`} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip labelFormatter={(v) => `t = ${Math.round(Number(v))} s`} contentStyle={{ background: "#1b2330", border: "1px solid #345", fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 10 }} />
          {series.map((s, i) => (
            <Line key={s.key} dataKey={s.key} name={s.label} dot={false} isAnimationActive={false} stroke={PALETTE[i % PALETTE.length]} strokeDasharray={s.dashed ? "5 3" : undefined} strokeWidth={1.6} />
          ))}
          {obs.length > 0 && <Scatter data={obs} dataKey="obs" name="observed / forecast" fill="#fff" shape="diamond" />}
          {limit && <ReferenceLine y={limit.value} stroke="#e74c3c" strokeDasharray="4 2" label={{ value: limit.label, fontSize: 9, fill: "#e74c3c", position: "insideTopRight" }} />}
          {now !== undefined && <ReferenceLine x={now} stroke="#ffd400" />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleLines({ rows, keys, height = 160 }: { rows: Record<string, number>[]; keys: { key: string; label: string }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows}>
        <CartesianGrid strokeDasharray="3 3" stroke="#334" />
        <XAxis dataKey="t" tick={{ fontSize: 10 }} />
        <YAxis tick={{ fontSize: 10 }} />
        <Tooltip />
        {keys.map((k, i) => (
          <Line key={k.key} dataKey={k.key} name={k.label} dot={false} isAnimationActive={false} stroke={PALETTE[i % PALETTE.length]} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

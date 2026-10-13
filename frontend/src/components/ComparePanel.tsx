import { useEffect, useState } from "react";
import { api, download } from "../api";
import { fmtNum } from "../lib/replay";
import { useStore } from "../store";
import { TimeChart } from "./Charts";
import { Empty, Section, Sel } from "./ui";

export default function ComparePanel() {
  const { runs, compare, set, loadRun, runData, time, fail, view } = useStore();
  const [res, setRes] = useState<any>(null);
  const done = runs.filter((r) => r.status === "completed").map((r) => ({ value: r.id, label: `${r.name} · ${r.engine === "jupedsim" ? "agents" : "CTM"} · ${r.id.slice(0, 6)}` }));

  useEffect(() => {
    setRes(null);
    if (!compare.a || !compare.b) return;
    (async () => {
      try {
        const [r] = await Promise.all([api.compare(compare.a!, compare.b!), loadRun(compare.a!), loadRun(compare.b!)]);
        setRes(r);
      } catch (e) {
        fail(e, "Comparing runs");
      }
    })();
  }, [compare.a, compare.b, loadRun, fail]);

  const A = compare.a ? runData[compare.a] : undefined;
  const B = compare.b ? runData[compare.b] : undefined;

  return (
    <div>
      <Section title="Choose runs">
        <Sel label="Baseline" value={compare.a} options={done} onChange={(v) => set({ compare: { ...compare, a: v || null } })} allowEmpty="— select —" />
        <Sel label="Alternative" value={compare.b} options={done} onChange={(v) => set({ compare: { ...compare, b: v || null } })} allowEmpty="— select —" />
        {compare.a && compare.b && (
          <div className="row wrap">
            <button className={view === "split" ? "active" : ""} onClick={() => set({ view: view === "split" ? "3d" : "split", time: 0 })}>
              {view === "split" ? "Exit split view" : "Synchronised 3D side-by-side"}
            </button>
            <button className="secondary" onClick={() => download(`/api/compare/report.pdf?a=${compare.a}&b=${compare.b}`)}>
              PDF
            </button>
            <button className="secondary" onClick={() => download(`/api/compare/export.csv?a=${compare.a}&b=${compare.b}`)}>
              CSV
            </button>
          </div>
        )}
      </Section>
      {!res && <Empty>Pick a baseline and an alternative (completed runs of this site).</Empty>}
      {res && (
        <>
          {res.warnings.map((w: string, i: number) => (
            <div key={i} className="alert warn small">
              {w}
            </div>
          ))}
          <Section title="Computed metrics (simulated estimates)">
            <table className="tbl compare">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Baseline</th>
                  <th>Alternative</th>
                  <th>Δ</th>
                </tr>
              </thead>
              <tbody>
                {res.rows.map((r: any) => (
                  <tr key={r.key} className={r.assessment === "alternative better" ? "better" : r.assessment === "alternative worse" ? "worse" : ""}>
                    <td>
                      {r.metric} {r.unit && <span className="muted small">({r.unit})</span>}
                    </td>
                    <td>{fmtNum(r.baseline, 2)}</td>
                    <td>{fmtNum(r.alternative, 2)}</td>
                    <td>
                      {r.difference === null ? "–" : `${r.difference > 0 ? "+" : ""}${fmtNum(r.difference, 2)}`}
                      {r.difference_pct !== null && Number.isFinite(r.difference_pct) && <span className="muted small"> ({r.difference_pct > 0 ? "+" : ""}{r.difference_pct.toFixed(0)}%)</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="muted small">Green/red marks a single metric only; it is not a safety assessment.</div>
          </Section>
          {A && B && (
            <Section title="Time series">
              <TimeChart
                title="Population in site"
                unit="persons"
                times={A.series.times}
                now={time}
                series={[
                  { key: "a", label: "baseline", values: A.series.total_in_site },
                  { key: "b", label: "alternative", values: B.series.total_in_site, times: B.series.times },
                ]}
              />
              <TimeChart
                title="Queued / congested persons"
                unit="persons"
                times={A.series.times}
                now={time}
                series={[
                  { key: "a", label: "baseline", values: A.series.queued },
                  { key: "b", label: "alternative", values: B.series.queued, times: B.series.times },
                ]}
              />
              <TimeChart
                title="Exited (all exits)"
                unit="persons"
                times={A.series.times}
                now={time}
                series={[
                  { key: "a", label: "baseline", values: sumSeries(A.series.exits, A.series.times.length) },
                  { key: "b", label: "alternative", values: sumSeries(B.series.exits, B.series.times.length), times: B.series.times },
                ]}
              />
            </Section>
          )}
        </>
      )}
    </div>
  );
}

function sumSeries(m: Record<string, number[]>, n: number): number[] {
  const out = new Array(n).fill(0);
  for (const v of Object.values(m)) for (let i = 0; i < n; i++) out[i] += v[i] ?? 0;
  return out;
}

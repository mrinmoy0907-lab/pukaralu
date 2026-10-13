import { useEffect, useState } from "react";
import { api, download } from "../api";
import { fmtNum, fmtTime } from "../lib/replay";
import { useStore } from "../store";
import type { Observation } from "../types";
import { TimeChart } from "./Charts";
import { Empty, Kpi, Section, Sel, Txt } from "./ui";

export default function ResultsPanel() {
  const { activeRun, runData, time, site, set, features, fail, reloadRuns } = useStore();
  const d = activeRun ? runData[activeRun] : undefined;
  const [zone, setZone] = useState<string>("");
  const [obs, setObs] = useState<Observation[]>([]);
  const [review, setReview] = useState<Record<string, string>>({});
  useEffect(() => {
    if (site) api.observations(site.id).then(setObs).catch(() => setObs([]));
  }, [site, activeRun]);
  useEffect(() => {
    if (d) {
      setReview({ status: d.run.review?.status ?? "draft", prepared_by: d.run.review?.prepared_by ?? "", reviewed_by: d.run.review?.reviewed_by ?? "", review_comments: d.run.review?.review_comments ?? "", approved_by: d.run.review?.approved_by ?? "" });
      const z = [...d.analysis.zones].sort((a, b) => b.max_density_ppm2 - a.max_density_ppm2)[0];
      setZone(z?.zone_id ?? "");
    }
  }, [d]);
  if (!d) return <Empty>Select a completed run in the Runs tab to see its results.</Empty>;
  const { analysis: a, series: s, run } = d;
  const sm = a.summary;
  const zrow = a.zones.find((z) => z.zone_id === zone);
  const zs = s.zones[zone];
  const zoneObs = obs.filter((o) => o.zone_fid === zone);

  async function saveReview() {
    try {
      const r = await api.review(run.id, review);
      set({ runData: { ...runData, [run.id]: { ...d!, run: { ...d!.run, review: r.review } } } });
      await reloadRuns();
    } catch (e) {
      fail(e, "Saving review");
    }
  }

  return (
    <div>
      <div className="result-head">
        <div>
          <strong>{run.name}</strong>
          <div className="muted small">
            {a.engine.method} · {a.engine.version} · seed {run.seed} · site v{run.site_version}
          </div>
        </div>
        <span className="badge sim">SIMULATED ESTIMATE</span>
      </div>
      {site?.is_synthetic && <div className="alert warn small">Synthetic demonstration site: results describe invented geometry, not a real ghat.</div>}
      {run.threshold_profile?.status !== "approved" && (
        <div className="alert warn small">Density thresholds used: "{run.threshold_profile?.name}" – status {String(run.threshold_profile?.status ?? "draft").toUpperCase()}. Limits must be approved by the competent authority.</div>
      )}
      <div className="kpis">
        <Kpi label="Peak in site" value={fmtNum(sm.peak_population_in_site, 0)} unit="persons" />
        <Kpi label="Max density (grid)" value={fmtNum(sm.max_density_ppm2, 2)} unit="p/m²" warn={sm.max_density_ppm2 > sm.density_limit_ppm2} title={`limit ${sm.density_limit_ppm2} p/m²`} />
        <Kpi label="Time above limit" value={fmtTime(sm.time_above_threshold_s)} warn={sm.time_above_threshold_s > 0} />
        <Kpi label="Bottlenecks (unresolved)" value={`${sm.n_bottlenecks} (${sm.n_unresolved_bottlenecks})`} warn={sm.n_unresolved_bottlenecks > 0} />
        <Kpi label="Avg / max entry wait" value={`${fmtTime(sm.avg_wait_s)} / ${fmtTime(sm.max_wait_s)}`} />
        <Kpi label="Throughput" value={fmtNum(sm.throughput_ppm, 1)} unit="p/min" />
        <Kpi label="Exited / arrived" value={`${fmtNum(sm.total_exited, 0)} / ${fmtNum(sm.total_arrivals + sm.initial_population, 0)}`} />
        <Kpi label="Remaining at end" value={fmtNum(sm.remaining_at_end, 0)} />
        {sm.mean_travel_time_s !== null && <Kpi label="Mean / p95 trip time" value={`${fmtTime(sm.mean_travel_time_s)} / ${fmtTime(sm.p95_travel_time_s)}`} />}
        {a.evacuation && (
          <Kpi
            label="Evacuation clearance"
            value={a.evacuation.cleared_within_simulation ? fmtTime(a.evacuation.clearance_time_s) : "not cleared"}
            warn={!a.evacuation.cleared_within_simulation}
          />
        )}
      </div>
      <Section title="Time series">
        <TimeChart
          title="Population"
          unit="persons"
          times={s.times}
          now={time}
          series={[
            { key: "in", label: "in site", values: s.total_in_site },
            { key: "q", label: "queued / congested", values: s.queued },
            ...Object.entries(s.entry_queues).map(([g, v]) => ({ key: `eq_${g}`, label: `entry queue ${g}`, values: v, dashed: true })),
          ]}
        />
        <TimeChart title="Exits (cumulative)" unit="persons" times={s.times} now={time} series={Object.entries(s.exits).map(([g, v]) => ({ key: `ex_${g}`, label: a.exits[g]?.name ?? g, values: v }))} />
        <Sel
          label="Zone"
          value={zone}
          options={[...a.zones].sort((x, y) => y.max_density_ppm2 - x.max_density_ppm2).map((z) => ({ value: z.zone_id, label: `${z.name} (max ${z.max_density_ppm2.toFixed(2)} p/m²)` }))}
          onChange={setZone}
        />
        {zs && zrow && (
          <>
            <TimeChart title={`Density – ${zrow.name}`} unit="p/m²" times={s.times} now={time} series={[{ key: "d", label: "density", values: zs.density }]} limit={{ value: zrow.limit_ppm2, label: `limit ${zrow.limit_ppm2}` }} />
            <TimeChart title={`Count – ${zrow.name}`} unit="persons" times={s.times} now={time} series={[{ key: "c", label: "simulated count", values: zs.count }]} observations={zoneObs} />
          </>
        )}
        {Object.keys(s.holding_occupancy_pct).length > 0 && (
          <TimeChart title="Holding-area occupancy" unit="% of limit" times={s.times} now={time} limit={{ value: 100, label: "limit" }} series={Object.entries(s.holding_occupancy_pct).map(([h, v]) => ({ key: `h_${h}`, label: h, values: v }))} />
        )}
      </Section>
      {a.events.length > 0 && (
        <Section title="Events">
          {a.events.map((e, i) => (
            <div key={i} className="event" onClick={() => set({ time: e.t })}>
              <code>{fmtTime(e.t)}</code> {e.text}
            </div>
          ))}
        </Section>
      )}
      {a.evacuation && (
        <Section title="Evacuation">
          <div className="small">
            Strategy <b>{a.evacuation.strategy}</b> · trigger {fmtTime(a.evacuation.trigger_s)} · evacuees {fmtNum(a.evacuation.evacuees, 0)} · unreachable {fmtNum(a.evacuation.unreachable_evacuees, 0)}
            <br />
            Total clearance: <b>{a.evacuation.cleared_within_simulation ? fmtTime(a.evacuation.clearance_time_s) : `not cleared (${fmtNum(a.evacuation.remaining_in_affected_area, 0)} remaining)`}</b> · capacity-constrained planning estimate (CCRP): {fmtTime(a.evacuation.ccrp_planning_estimate_s)}
          </div>
          <table className="tbl">
            <thead>
              <tr>
                <th>Zone</th>
                <th>At trigger</th>
                <th>Clearance</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(a.evacuation.clearance_by_zone).map(([z, v]) => (
                <tr key={z}>
                  <td>{v.name}</td>
                  <td>{fmtNum(v.population_at_trigger, 0)}</td>
                  <td className={v.clearance_s === null ? "warn-text" : ""}>{v.clearance_s === null ? "not cleared" : fmtTime(v.clearance_s)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="alert info small">{a.evacuation.note}</div>
        </Section>
      )}
      <Section title={`Bottlenecks (${a.bottlenecks.length})`}>
        {!a.bottlenecks.length && <div className="muted small">No location exceeded its limit for the minimum duration.</div>}
        {a.bottlenecks.slice(0, 20).map((b, i) => (
          <div key={i} className="event">
            <b>B{i + 1}</b> {b.type} near {b.near}: {b.max_density_ppm2} p/m² for {fmtTime(b.duration_s)} {b.unresolved && <span className="warn-text">(unresolved at end)</span>}
          </div>
        ))}
      </Section>
      <Section title="Exit utilisation">
        <table className="tbl">
          <thead>
            <tr>
              <th>Exit</th>
              <th>Persons</th>
              <th>Share</th>
              <th>Peak / capacity</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(a.exits).map(([k, e]) => (
              <tr key={k}>
                <td>{e.name}</td>
                <td>{fmtNum(e.count, 0)}</td>
                <td>{(e.share * 100).toFixed(0)}%</td>
                <td>
                  {fmtNum(e.peak_ppm, 0)} / {fmtNum(e.capacity_ppm, 0)} p/min
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      {a.holding.length > 0 && (
        <Section title="Holding-area capacity">
          {a.holding.map((h) => (
            <div key={h.holding_id} className="card">
              <b>{h.name}</b>
              <div className="small">
                Usable {fmtNum(h.usable_area_m2, 0)} m² (excluded {fmtNum(h.excluded_area_m2, 0)} m²) · limit {fmtNum(h.effective_limit, 0)} persons
                {h.configured_capacity ? ` (configured ${h.configured_capacity}; density-based ${fmtNum(h.density_limit_ppm2 * h.usable_area_m2, 0)})` : " (density-based)"}
                <br />
                Peak {fmtNum(h.peak_population, 0)} ({h.peak_occupancy_pct.toFixed(0)}%) · now available {fmtNum(h.available_capacity_final, 0)}
                {h.time_limit_reached_s !== null && <span className="warn-text"> · limit reached at {fmtTime(h.time_limit_reached_s)}</span>}
                {h.projected_time_to_limit_s !== null && <> · projected to reach limit in {fmtTime(h.projected_time_to_limit_s)}</>}
              </div>
              {h.suggestions.map((x, i) => (
                <div key={i} className="small suggestion">
                  → {x}
                </div>
              ))}
            </div>
          ))}
        </Section>
      )}
      <Section title="Zones" open={false}>
        <table className="tbl">
          <thead>
            <tr>
              <th>Zone</th>
              <th>Max p/m²</th>
              <th>Limit</th>
              <th>Above (s)</th>
              <th>Max n</th>
            </tr>
          </thead>
          <tbody>
            {[...a.zones]
              .sort((x, y) => y.max_density_ppm2 - x.max_density_ppm2)
              .map((z) => (
                <tr key={z.zone_id} className={z.exceeds_limit ? "warn-row" : ""} onClick={() => set({ selected: z.zone_id })}>
                  <td>{z.name}</td>
                  <td>{z.max_density_ppm2.toFixed(2)}</td>
                  <td>{z.limit_ppm2}</td>
                  <td>{z.time_above_limit_s.toFixed(0)}</td>
                  <td>{z.max_count.toFixed(0)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </Section>
      <Section title="Suggested interventions (for expert review)">
        {a.interventions.map((x, i) => (
          <div key={i} className="small suggestion">
            • {x}
          </div>
        ))}
        {a.warnings.length > 0 && (
          <details>
            <summary className="small">Model warnings ({a.warnings.length})</summary>
            {a.warnings.map((w, i) => (
              <div key={i} className="small warn-text">
                {w}
              </div>
            ))}
          </details>
        )}
      </Section>
      <Section title="Exports">
        <div className="row wrap">
          <button onClick={() => download(`/api/runs/${run.id}/report.pdf`)}>PDF report</button>
          <button className="secondary" onClick={() => download(`/api/runs/${run.id}/export.zip`)}>CSV (zip)</button>
          <button className="secondary" onClick={() => download(`/api/runs/${run.id}/density.geojson`)}>Max-density GeoJSON</button>
          <button className="secondary" onClick={() => download(`/api/runs/${run.id}/bottlenecks.geojson`)}>Bottlenecks GeoJSON</button>
          {run.scenario_id && (
            <button className="secondary" onClick={() => download(`/api/scenarios/${run.scenario_id}/layout.geojson`)}>
              Layout GeoJSON
            </button>
          )}
        </div>
      </Section>
      <Section title="Review & approval" open={false}>
        <Sel label="Status" value={review.status} options={["draft", "reviewed", "approved", "rejected"].map((x) => ({ value: x, label: x }))} onChange={(v) => setReview({ ...review, status: v })} />
        <Txt label="Prepared by" value={review.prepared_by ?? ""} onChange={(v) => setReview({ ...review, prepared_by: v })} />
        <Txt label="Reviewed by" value={review.reviewed_by ?? ""} onChange={(v) => setReview({ ...review, reviewed_by: v })} />
        <Txt label="Comments" value={review.review_comments ?? ""} onChange={(v) => setReview({ ...review, review_comments: v })} area />
        <Txt label="Approved by (authorised official)" value={review.approved_by ?? ""} onChange={(v) => setReview({ ...review, approved_by: v })} />
        <button onClick={saveReview}>Save review record</button>
        <div className="muted small">The record is printed on the PDF. It does not change the results.</div>
      </Section>
      <div className="muted small" style={{ padding: 8 }}>
        {features.length} site features · run {run.id.slice(0, 8)} · data hash {run.features_hash.slice(0, 10)}
      </div>
    </div>
  );
}

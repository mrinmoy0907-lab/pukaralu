import { useEffect, useRef } from "react";
import { api } from "../api";
import { fmtTime } from "../lib/replay";
import { useStore } from "../store";
import type { Run } from "../types";
import { Section } from "./ui";

/** Subscribe to server-sent progress events of unfinished runs. */
function useRunEvents(runs: Run[]) {
  const sources = useRef<Map<string, EventSource>>(new Map());
  useEffect(() => {
    const active = runs.filter((r) => r.status === "queued" || r.status === "running");
    for (const r of active) {
      if (sources.current.has(r.id)) continue;
      const es = new EventSource(`/api/runs/${r.id}/events`);
      es.onmessage = (ev) => {
        const d = JSON.parse(ev.data);
        const st = useStore.getState();
        st.set({ runs: st.runs.map((x) => (x.id === d.id ? { ...x, ...d } : x)) });
        if (["completed", "failed", "cancelled"].includes(d.status)) {
          es.close();
          sources.current.delete(r.id);
          st.reloadRuns();
          if (d.status === "completed") st.toast("success", `Simulation '${r.name}' completed.`);
          if (d.status === "failed") st.toast("error", `Simulation '${r.name}' failed`, [d.error ?? ""]);
        }
      };
      es.onerror = () => {
        es.close();
        sources.current.delete(r.id);
      };
      sources.current.set(r.id, es);
    }
  }, [runs]);
  useEffect(() => () => sources.current.forEach((s) => s.close()), []);
}

export default function RunsPanel() {
  const { runs, activeRun, setActiveRun, reloadRuns, compare, set, fail, toast, busy } = useStore();
  useRunEvents(runs);

  async function act(fn: () => Promise<unknown>, label: string) {
    try {
      await fn();
      await reloadRuns();
    } catch (e) {
      fail(e, label);
    }
  }

  return (
    <div>
      <Section title="Simulation runs" right={<button className="icon" onClick={() => reloadRuns()} title="refresh">⟳</button>}>
        {!runs.length && <div className="muted">No runs yet. Open the Scenarios tab and press ▶ Run.</div>}
        <div className="list">
          {runs.map((r) => (
            <div key={r.id} className={`list-item col ${activeRun === r.id ? "active" : ""}`}>
              <div className="row spread">
                <strong>{r.name}</strong>
                <span className={`status ${r.status}`}>{r.status}</span>
              </div>
              <div className="muted small">
                {r.engine === "jupedsim" ? "Agent-based (JuPedSim)" : "Macroscopic (CTM)"} · seed {r.seed} · {r.created_at?.slice(0, 16).replace("T", " ")}
                {r.review?.status && r.review.status !== "draft" && <> · review: {r.review.status}</>}
              </div>
              {(r.status === "running" || r.status === "queued") && (
                <div className="progress">
                  <div style={{ width: `${Math.round(r.progress * 100)}%` }} />
                  <span>
                    {Math.round(r.progress * 100)}% {r.message}
                  </span>
                </div>
              )}
              {r.status === "failed" && <div className="warn-text small">{r.error}</div>}
              {r.status === "completed" && r.summary && (
                <div className="muted small">
                  peak {Math.round(r.summary.peak_population_in_site)} persons · max {r.summary.max_density_ppm2.toFixed(2)} p/m² · {r.summary.n_bottlenecks} bottleneck(s)
                  {r.summary.clearance_time_s !== null && <> · clearance {fmtTime(r.summary.clearance_time_s)}</>}
                </div>
              )}
              <div className="row wrap">
                {r.status === "completed" && (
                  <button className="small" onClick={() => setActiveRun(r.id)} disabled={!!busy[r.id]}>
                    {busy[r.id] ? "Loading…" : activeRun === r.id ? "Showing" : "View results"}
                  </button>
                )}
                {r.status === "completed" && (
                  <>
                    <button className={`small secondary ${compare.a === r.id ? "active" : ""}`} onClick={() => set({ compare: { ...compare, a: r.id } })}>
                      Baseline
                    </button>
                    <button className={`small secondary ${compare.b === r.id ? "active" : ""}`} onClick={() => set({ compare: { ...compare, b: r.id } })}>
                      Alternative
                    </button>
                  </>
                )}
                {(r.status === "running" || r.status === "queued") && (
                  <button className="small danger" onClick={() => act(() => api.cancelRun(r.id), "Cancel")}>
                    Cancel
                  </button>
                )}
                {r.status !== "running" && r.status !== "queued" && (
                  <button className="small secondary" title="Re-run with the stored inputs, data snapshot and seed" onClick={() => act(async () => (await api.rerun(r.id), toast("info", "Reproduction run started.")), "Reproduce")}>
                    Reproduce
                  </button>
                )}
                <button
                  className="small secondary"
                  onClick={() => confirm("Delete this run and its results?") && act(async () => {
                    await api.deleteRun(r.id);
                    if (activeRun === r.id) setActiveRun(null);
                  }, "Delete")}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

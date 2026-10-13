import { useEffect, useRef } from "react";
import { BAND_COLOURS, bandLabels } from "../lib/colors";
import { fmtTime } from "../lib/replay";
import { useStore } from "../store";

export default function Timeline({ runIds }: { runIds: string[] }) {
  const { time, playing, speed, set, runData, profiles } = useStore();
  const datas = runIds.map((id) => runData[id]).filter(Boolean);
  const duration = Math.max(0, ...datas.map((d) => d.series.times[d.series.times.length - 1] ?? 0));
  const events = datas.flatMap((d) => d.analysis.events);
  const last = useRef<number | null>(null);

  useEffect(() => {
    if (!playing) {
      last.current = null;
      return;
    }
    let raf = 0;
    const tick = (ts: number) => {
      if (last.current !== null) {
        const dt = (ts - last.current) / 1000;
        const st = useStore.getState();
        const t = st.time + dt * st.speed;
        if (t >= duration) {
          st.set({ time: duration, playing: false });
          return;
        }
        st.set({ time: t });
      }
      last.current = ts;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, duration]);

  if (!datas.length) return null;
  const bands = (datas[0].run.threshold_profile?.density_bands as number[]) ?? profiles[0]?.values.density_bands ?? [];
  return (
    <div className="timeline">
      <button onClick={() => set({ playing: !playing, time: time >= duration ? 0 : time })} title="play / pause">
        {playing ? "❚❚" : "▶"}
      </button>
      <button className="secondary" onClick={() => set({ time: 0, playing: false })} title="restart">
        ⏮
      </button>
      <select value={speed} onChange={(e) => set({ speed: Number(e.target.value) })} title="replay speed">
        {[1, 2, 5, 10, 20, 60].map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>
      <div className="scrub">
        <input type="range" min={0} max={duration} step={0.5} value={Math.min(time, duration)} onChange={(e) => set({ time: Number(e.target.value), playing: false })} />
        <div className="event-marks">
          {events.map((e, i) => (
            <span key={i} style={{ left: `${(e.t / Math.max(duration, 1)) * 100}%` }} title={`${fmtTime(e.t)} ${e.text}`} className={`mark ${e.type}`} />
          ))}
        </div>
      </div>
      <span className="clock">
        {fmtTime(time)} / {fmtTime(duration)}
      </span>
      <div className="legend compact" title="density, persons/m² (configurable thresholds)">
        {bandLabels(bands).map((l, i) => (
          <span key={i}>
            <i style={{ background: BAND_COLOURS[i] }} />
            {l}
          </span>
        ))}
        <span className="muted">p/m²</span>
      </div>
    </div>
  );
}

import { useMemo, useState } from "react";
import { api } from "../api";
import { fmtNum, fmtTime } from "../lib/replay";
import { useStore } from "../store";
import { Check, MultiCheck, Section, Sel } from "./ui";

export default function LayersPanel() {
  const { meta, overlays, features, site, network, routeResult, set, toast, fail } = useStore();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [k, setK] = useState(3);
  const [closed, setClosed] = useState<string[]>([]);
  const [emerg, setEmerg] = useState(false);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of features) c[f.properties.pk_type] = (c[f.properties.pk_type] ?? 0) + 1;
    return c;
  }, [features]);

  const nodesOpts = features
    .filter((f) => ["gate", "holding_area", "bathing_area", "ghat", "plaza", "assembly_point", "bus_terminal", "transit_hub", "parking"].includes(f.properties.pk_type))
    .map((f) => ({ value: String(f.id), label: `${f.properties.name ?? f.id} (${f.properties.pk_type})` }));
  const corridorOpts = features
    .filter((f) => f.properties.pk_type === "corridor" || f.properties.pk_type === "emergency_corridor")
    .map((f) => ({ value: String(f.id), label: f.properties.name ?? String(f.id) }));

  async function toggleNetwork(v: boolean) {
    set({ overlays: { ...overlays, network: v } });
    if (v && site) {
      try {
        const n = await api.network(site.id);
        set({ network: n });
        if (n.warnings?.length) toast("info", `Network: ${n.warnings.length} warning(s)`, n.warnings);
      } catch (e) {
        fail(e, "Building network");
      }
    }
  }

  async function findRoutes() {
    if (!site || !from || !to) return;
    try {
      const r = await api.routes(site.id, { from_id: from, to_id: to, k, closed_corridors: closed, allow_emergency: emerg });
      set({ routeResult: r, overlays: { ...overlays, routes: true } });
      if (r.unreachable) toast("error", "Destination unreachable with these closures", [r.message]);
    } catch (e) {
      fail(e, "Route search");
    }
  }

  return (
    <div>
      <h2 className="page-title">Planning workbench</h2>
      <p className="muted small">Use the map toolbar to select, draw zones, obstructions, gates (More… for corridors, holding areas, ghats, barricades …), edit vertices and delete. Drawing and editing use the 2D map; layers and basemap are in the Layers menu.</p>
      <Section title="Feature counts">
        <div className="chips">
          {Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([t, n]) => (
            <span key={t} className="pill neutral">{meta?.feature_types[t]?.label ?? t}: {n}</span>
          ))}
        </div>
      </Section>
      <Section title="Simulation overlays">
        <Check label="Animated agents (agent-based runs)" checked={overlays.agents} onChange={(v) => set({ overlays: { ...overlays, agents: v } })} />
        <Check label="Density heatmap" checked={overlays.density} onChange={(v) => set({ overlays: { ...overlays, density: v } })} />
        <Check label="Corridor flows (macroscopic runs)" checked={overlays.flows} onChange={(v) => set({ overlays: { ...overlays, flows: v } })} />
        <Check label="Bottleneck markers" checked={overlays.bottlenecks} onChange={(v) => set({ overlays: { ...overlays, bottlenecks: v } })} />
        <Check label="Pedestrian network (nodes/links)" checked={overlays.network} onChange={toggleNetwork} />
        {overlays.network && network && (
          <div className="muted small">
            {network.stats.nodes} nodes · {network.stats.links} directed links · walkable {fmtNum(network.stats.walkable_area_m2, 0)} m² ·{" "}
            {network.stats.connected_components} component(s)
            {network.warnings.map((w: string, i: number) => (
              <div key={i} className="warn-text">⚠ {w}</div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Route explorer (alternative routes)">
        <Sel label="From" value={from} options={nodesOpts} onChange={setFrom} allowEmpty="— select —" />
        <Sel label="To" value={to} options={nodesOpts} onChange={setTo} allowEmpty="— select —" />
        <Sel label="Alternatives" value={String(k)} options={[1, 2, 3, 4, 5].map((x) => ({ value: String(x), label: String(x) }))} onChange={(v) => setK(Number(v))} />
        <div className="muted small">Treat as closed:</div>
        <MultiCheck options={corridorOpts} value={closed} onChange={setClosed} />
        <Check label="Allow emergency-only corridors" checked={emerg} onChange={setEmerg} />
        <button onClick={findRoutes} disabled={!from || !to}>
          Find routes
        </button>
        {routeResult?.routes?.length > 0 && (
          <table className="tbl">
            <thead>
              <tr>
                <th>#</th>
                <th>Length</th>
                <th>Free-flow time</th>
                <th title="Capacity of the narrowest link">Bottleneck cap.</th>
              </tr>
            </thead>
            <tbody>
              {routeResult.routes.map((r: any, i: number) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{fmtNum(r.length_m, 0)} m</td>
                  <td>{fmtTime(r.free_flow_time_s)}</td>
                  <td>{fmtNum(r.bottleneck_capacity_ppm, 0)} p/min</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {routeResult && <p className="muted small">{routeResult.method}. Free-flow time ignores congestion; use a simulation to assess loaded conditions.</p>}
      </Section>
    </div>
  );
}

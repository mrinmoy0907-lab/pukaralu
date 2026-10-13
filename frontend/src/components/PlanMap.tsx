import { useEffect, useMemo, useRef } from "react";
import OlMap from "ol/Map";
import View from "ol/View";
import GeoJSON from "ol/format/GeoJSON";
import TileLayer from "ol/layer/Tile";
import VectorLayer from "ol/layer/Vector";
import OSM from "ol/source/OSM";
import XYZ from "ol/source/XYZ";
import VectorSource from "ol/source/Vector";
import { Circle as CircleStyle, Fill, Stroke, Style, Text } from "ol/style";
import { Draw, Modify, Select } from "ol/interaction";
import { click } from "ol/events/condition";
import { fromLonLat } from "ol/proj";
import Collection from "ol/Collection";
import OlFeature from "ol/Feature";
import { Point, Polygon } from "ol/geom";
import type { FeatureLike } from "ol/Feature";
import { LAYER_GROUPS, POINT_SYMBOL, TYPE_STYLE, densityColour } from "../lib/colors";
import { denseFrame, frameIndex } from "../lib/replay";
import { api } from "../api";
import { useStore } from "../store";
import type { Feature } from "../types";

const fmt = new GeoJSON({ dataProjection: "EPSG:4326", featureProjection: "EPSG:3857" });

const DRAW_DEFAULTS: Record<string, Record<string, any>> = {
  corridor: { width_m: 4, direction: "both", surface: "path", enabled: true },
  emergency_corridor: { width_m: 5, direction: "both", emergency_only: true, enabled: true },
  gate: { role: "both", width_m: 4, enabled: true },
  holding_area: { capacity_persons: null },
  building: { height_m: 8 },
  temple: { height_m: 15 },
  wall: { height_m: 2.5 },
  barricade: { height_m: 1.1 },
};

function styleFor(f: FeatureLike, selected: string | null, resolution: number): Style | Style[] {
  const t = f.get("pk_type") as string;
  const st = TYPE_STYLE[t] ?? { fill: "rgba(200,200,200,0.5)", stroke: "#999" };
  const sel = String(f.getId()) === selected;
  const geomType = f.getGeometry()?.getType();
  if (geomType === "Point") {
    let col = st.fill;
    if (t === "gate") col = f.get("emergency_exit") ? "#e67e22" : f.get("role") === "entry" ? "#27ae60" : f.get("role") === "exit" ? "#c0392b" : "#2980b9";
    if (f.get("enabled") === false) col = "#7f8c8d";
    return new Style({
      image: new CircleStyle({ radius: sel ? 9 : 7, fill: new Fill({ color: col }), stroke: new Stroke({ color: sel ? "#ff0" : "#fff", width: 2 }) }),
      text: new Text({ text: POINT_SYMBOL[t] ?? "", fill: new Fill({ color: "#fff" }), font: "bold 9px sans-serif" }),
    });
  }
  if (t === "corridor" || t === "emergency_corridor") {
    const px = Math.max(2, Number(f.get("width_m") ?? 4) / resolution);
    const off = f.get("enabled") === false;
    return [
      new Style({ stroke: new Stroke({ color: sel ? "#ffd400" : off ? "rgba(220,0,0,0.7)" : st.fill, width: px, lineCap: "round", lineJoin: "round" }) }),
      new Style({ stroke: new Stroke({ color: st.stroke, width: 1, lineDash: f.get("direction") !== "both" ? [6, 4] : undefined }) }),
    ];
  }
  return new Style({
    fill: new Fill({ color: sel ? "rgba(255,230,0,0.5)" : st.fill }),
    stroke: new Stroke({ color: sel ? "#ffd400" : st.stroke, width: sel ? 3 : t === "wall" || t === "barricade" ? 3 : 1.2 }),
  });
}

export default function PlanMap({ runId }: { runId: string | null }) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<OlMap | null>(null);
  const featSrc = useRef(new VectorSource());
  const simSrc = useRef(new VectorSource());
  const overlaySrc = useRef(new VectorSource());
  const featLayer = useRef<VectorLayer<VectorSource> | null>(null);
  const baseLayer = useRef<TileLayer<any> | null>(null);
  const drawRef = useRef<Draw | null>(null);
  const modifyRef = useRef<Modify | null>(null);

  const site = useStore((s) => s.site);
  const features = useStore((s) => s.features);
  const selected = useStore((s) => s.selected);
  const hidden = useStore((s) => s.hiddenGroups);
  const drawType = useStore((s) => s.drawType);
  const meta = useStore((s) => s.meta);
  const runData = useStore((s) => (runId ? s.runData[runId] : undefined));
  const time = useStore((s) => s.time);
  const overlays = useStore((s) => s.overlays);
  const network = useStore((s) => s.network);
  const routeResult = useStore((s) => s.routeResult);
  const profiles = useStore((s) => s.profiles);
  const bands = useMemo(() => (runData?.run.threshold_profile?.density_bands as number[]) ?? profiles[0]?.values.density_bands ?? [0.5, 1, 2, 3, 4, 5], [runData, profiles]);

  useEffect(() => {
    if (!el.current) return;
    baseLayer.current = new TileLayer({ source: new OSM(), visible: false });
    featLayer.current = new VectorLayer({
      source: featSrc.current,
      style: (f, res) => styleFor(f, useStore.getState().selected, res),
    });
    const map = new OlMap({
      target: el.current,
      layers: [
        baseLayer.current,
        featLayer.current,
        new VectorLayer({ source: overlaySrc.current }),
        new VectorLayer({ source: simSrc.current }),
      ],
      view: new View({ center: fromLonLat([85, 15]), zoom: 16 }),
    });
    const select = new Select({ condition: click, layers: [featLayer.current], style: null });
    select.on("select", (e) => {
      const f = e.selected[0];
      useStore.getState().set({ selected: f ? String(f.getId()) : null });
    });
    map.addInteraction(select);
    mapRef.current = map;
    return () => map.setTarget(undefined);
  }, []);

  // basemap
  useEffect(() => {
    if (!site || !baseLayer.current) return;
    const custom = import.meta.env.VITE_BASEMAP_URL as string | undefined;
    if (custom) baseLayer.current.setSource(new XYZ({ url: custom, attributions: (import.meta.env.VITE_BASEMAP_ATTRIBUTION as string) || "" }));
    baseLayer.current.setVisible(site.basemap === "osm" || !!custom);
  }, [site]);

  // features
  useEffect(() => {
    const hide = new Set<string>();
    for (const g of LAYER_GROUPS) if (hidden[g.key]) g.types.forEach((t) => hide.add(t));
    featSrc.current.clear();
    const fs = fmt.readFeatures({ type: "FeatureCollection", features: features.filter((f) => !hide.has(f.properties.pk_type)) });
    featSrc.current.addFeatures(fs);
    featLayer.current?.changed();
  }, [features, hidden]);

  useEffect(() => featLayer.current?.changed(), [selected]);

  // zoom to site
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !features.length) return;
    const ext = featSrc.current.getExtent();
    if (ext && Number.isFinite(ext[0])) map.getView().fit(ext, { padding: [40, 40, 40, 40], maxZoom: 19 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site?.id, features.length > 0]);

  // drawing
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (drawRef.current) map.removeInteraction(drawRef.current);
    drawRef.current = null;
    if (!drawType || !meta || !site) return;
    const geom = meta.feature_types[drawType]?.geom ?? "Polygon";
    const draw = new Draw({ source: new VectorSource(), type: geom });
    draw.on("drawend", async (e) => {
      const gj = JSON.parse(fmt.writeFeature(e.feature)) as Feature;
      const name = window.prompt(`Name for the new ${meta.feature_types[drawType].label}:`, meta.feature_types[drawType].label);
      if (name === null) return;
      try {
        const created = await api.createFeature(site.id, {
          type: "Feature",
          geometry: gj.geometry,
          properties: { pk_type: drawType, name, ...(DRAW_DEFAULTS[drawType] ?? {}) },
        });
        await useStore.getState().reloadFeatures();
        useStore.getState().set({ selected: String(created.id) });
        useStore.getState().toast("success", `Added ${name}. Edit its attributes in the inspector.`);
      } catch (err) {
        useStore.getState().fail(err, "Saving feature");
      }
    });
    map.addInteraction(draw);
    drawRef.current = draw;
  }, [drawType, meta, site]);

  // modify selected feature geometry
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (modifyRef.current) map.removeInteraction(modifyRef.current);
    modifyRef.current = null;
    if (!selected || drawType || !site) return;
    const f = featSrc.current.getFeatureById(selected);
    if (!f) return;
    const modify = new Modify({ features: new Collection([f]) });
    modify.on("modifyend", async () => {
      const gj = JSON.parse(fmt.writeFeature(f)) as Feature;
      const orig = useStore.getState().features.find((x) => String(x.id) === selected);
      if (!orig) return;
      try {
        await api.updateFeature(site.id, { ...orig, geometry: gj.geometry });
        await useStore.getState().reloadFeatures();
      } catch (err) {
        useStore.getState().fail(err, "Updating geometry");
        await useStore.getState().reloadFeatures();
      }
    });
    map.addInteraction(modify);
    modifyRef.current = modify;
  }, [selected, drawType, site, features]);

  // static overlays: network, routes, bottlenecks
  useEffect(() => {
    overlaySrc.current.clear();
    const add = (geom: any, style: Style) => {
      const f = fmt.readFeature({ type: "Feature", geometry: geom, properties: {} }) as OlFeature;
      f.setStyle(style);
      overlaySrc.current.addFeature(f);
    };
    if (overlays.network && network) {
      for (const f of network.features)
        add(f.geometry, f.properties.kind === "link"
          ? new Style({ stroke: new Stroke({ color: f.properties.emergency_only ? "orange" : "rgba(0,200,220,0.9)", width: 1.5 }) })
          : new Style({ image: new CircleStyle({ radius: 3, fill: new Fill({ color: "#00c8dc" }) }) }));
    }
    if (overlays.routes && routeResult?.routes) {
      const cols = ["#32cd32", "#ff00ff", "#ffd700", "#00ffff", "#ffa500"];
      routeResult.routes.forEach((r: any, i: number) => add(r.geometry, new Style({ stroke: new Stroke({ color: cols[i % cols.length], width: 6 - i }) })));
    }
    if (runData && overlays.bottlenecks) {
      runData.analysis.bottlenecks.slice(0, 20).forEach((b, i) =>
        add({ type: "Point", coordinates: [b.lon, b.lat] }, new Style({
          image: new CircleStyle({ radius: 10, fill: new Fill({ color: "rgba(255,0,0,0.25)" }), stroke: new Stroke({ color: "red", width: 2 }) }),
          text: new Text({ text: `B${i + 1}`, offsetY: -16, fill: new Fill({ color: "#900" }), font: "bold 11px sans-serif" }),
        })));
    }
  }, [network, routeResult, runData, overlays]);

  // per-frame overlays: density cells and agents
  useEffect(() => {
    simSrc.current.clear();
    if (!runData) return;
    const out: OlFeature[] = [];
    if (overlays.density) {
      const g = runData.grid;
      const fi = frameIndex(g.times, time);
      const dense = denseFrame(g, g.frames[fi]);
      const gd = g.grid;
      const dlon = (gd.east - gd.west) / gd.nx;
      const dlat = (gd.north - gd.south) / gd.ny;
      for (let i = 0; i < dense.length; i++) {
        const v = dense[i];
        if (v < 0.05) continue;
        const iy = Math.floor(i / gd.nx);
        const ix = i % gd.nx;
        const x0 = gd.west + ix * dlon;
        const y0 = gd.south + iy * dlat;
        const ring = [[x0, y0], [x0 + dlon, y0], [x0 + dlon, y0 + dlat], [x0, y0 + dlat], [x0, y0]].map((c) => fromLonLat(c));
        const f = new OlFeature(new Polygon([ring]));
        f.setStyle(new Style({ fill: new Fill({ color: densityColour(v, bands) + "aa" }) }));
        out.push(f);
      }
    }
    if (overlays.agents && runData.agents) {
      const fr = runData.agents[frameIndex(runData.agents.map((a) => a.t), time)];
      const st = new Style({ image: new CircleStyle({ radius: 2, fill: new Fill({ color: "#ff6f00" }) }) });
      if (fr)
        for (let i = 0; i < fr.ids.length; i++) {
          const f = new OlFeature(new Point(fromLonLat([fr.lon[i], fr.lat[i]])));
          f.setStyle(st);
          out.push(f);
        }
    }
    simSrc.current.addFeatures(out);
  }, [time, runData, overlays, bands]);

  return (
    <div className="plan-wrap">
      <div ref={el} className="plan-map" />
      <div className="view-badges">
        {site?.is_synthetic && <span className="badge warn">SYNTHETIC SITE – not surveyed data</span>}
        {drawType && <span className="badge dark">Drawing: {meta?.feature_types[drawType]?.label} – double-click to finish</span>}
        {site && site.basemap === "osm" && <span className="badge dark">© OpenStreetMap contributors</span>}
      </div>
    </div>
  );
}


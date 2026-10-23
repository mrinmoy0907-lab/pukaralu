import * as Cesium from "cesium";
import { useEffect, useMemo, useRef, useState } from "react";
import { BAND_COLOURS, LAYER_GROUPS, POINT_SYMBOL, TYPE_STYLE, bandIndex } from "../lib/colors";
import { denseFrame, fmtTime, frameIndex } from "../lib/replay";
import { basemapFor } from "../lib/basemaps";
import { sampleHeight, tileHeights } from "../lib/terrain";
import { useStore } from "../store";
import type { Feature, RunData, Terrain } from "../types";

// No Cesium ion services are used: imagery and terrain come from configurable open sources.
Cesium.Ion.defaultAccessToken = "";

/** Camera synchronisation between the two viewers of the split (comparison) view. */
const cameraBus = new EventTarget();

const OBSTACLE_EXTRUDE = new Set(["building", "temple", "obstacle"]);

function cssColor(c: string, alpha?: number): Cesium.Color {
  const col = Cesium.Color.fromCssColorString(c);
  return alpha === undefined ? col : col.withAlpha(alpha);
}

function hiddenTypes(hidden: Record<string, boolean>): Set<string> {
  const s = new Set<string>();
  for (const g of LAYER_GROUPS) if (hidden[g.key]) g.types.forEach((t) => s.add(t));
  return s;
}

function ringPositions(ring: [number, number][], terrain: Terrain | null, offset: number | null) {
  if (offset === null) return Cesium.Cartesian3.fromDegreesArray(ring.flat());
  return Cesium.Cartesian3.fromDegreesArrayHeights(ring.flatMap(([x, y]) => [x, y, sampleHeight(terrain, x, y) + offset]));
}

function makeTerrain(t: Terrain): Cesium.TerrainProvider {
  const size = 33;
  const scheme = new Cesium.GeographicTilingScheme();
  return new Cesium.CustomHeightmapTerrainProvider({
    width: size,
    height: size,
    tilingScheme: scheme,
    callback: (x: number, y: number, level: number) => {
      const r = scheme.tileXYToRectangle(x, y, level);
      return tileHeights(
        t,
        Cesium.Math.toDegrees(r.west),
        Cesium.Math.toDegrees(r.south),
        Cesium.Math.toDegrees(r.east),
        Cesium.Math.toDegrees(r.north),
        size,
      );
    },
  });
}

interface Props {
  runId: string | null;
  syncId?: string;
  title?: string;
}

export default function CesiumView({ runId, syncId, title }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const featuresDs = useRef<Cesium.CustomDataSource | null>(null);
  const overlayDs = useRef<Cesium.CustomDataSource | null>(null);
  const modelsDs = useRef<Cesium.CustomDataSource | null>(null);
  const calcDs = useRef<Cesium.CustomDataSource | null>(null);
  const points = useRef<Cesium.PointPrimitiveCollection | null>(null);
  const pointById = useRef<Map<number, Cesium.PointPrimitive>>(new Map());
  const densityPrim = useRef<Cesium.Primitive | null>(null);
  const densityCells = useRef<number[]>([]);
  const [primTick, setPrimTick] = useState(0);
  const linkEntities = useRef<{ entity: Cesium.Entity; members: number[] }[]>([]);
  const timeLabel = useRef<HTMLDivElement>(null);
  const hovering = useRef(false);

  const site = useStore((s) => s.site);
  const features = useStore((s) => s.features);
  const terrain = useStore((s) => s.terrain);
  const hidden = useStore((s) => s.hiddenGroups);
  const selected = useStore((s) => s.selected);
  const overlays = useStore((s) => s.overlays);
  const network = useStore((s) => s.network);
  const routeResult = useStore((s) => s.routeResult);
  const runData: RunData | undefined = useStore((s) => (runId ? s.runData[runId] : undefined));
  const profiles = useStore((s) => s.profiles);
  const time = useStore((s) => s.time);
  const set = useStore((s) => s.set);
  const basemap = useStore((s) => s.basemap);
  const baseLayers = useStore((s) => s.baseLayers);
  const focus = useStore((s) => s.focus);
  const areaCalc = useStore((s) => s.areaCalc);
  const snapping = useStore((s) => s.snapping);

  const bands: number[] = useMemo(
    () => (runData?.run.threshold_profile?.density_bands as number[]) ?? profiles[0]?.values.density_bands ?? [0.5, 1, 1.5, 2, 3, 4, 5],
    [runData, profiles],
  );

  // ------------------------------------------------------------------ viewer
  useEffect(() => {
    if (!container.current) return;
    const viewer = new Cesium.Viewer(container.current, {
      baseLayer: false,
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: true,
      navigationHelpButton: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      infoBox: false,
      selectionIndicator: false,
      requestRenderMode: false,
    });
    viewer.scene.globe.depthTestAgainstTerrain = false;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString("#2a3340");
    (viewer.cesiumWidget.creditContainer as HTMLElement).style.fontSize = "10px";
    featuresDs.current = new Cesium.CustomDataSource("features");
    overlayDs.current = new Cesium.CustomDataSource("overlays");
    modelsDs.current = new Cesium.CustomDataSource("models");
    calcDs.current = new Cesium.CustomDataSource("area");
    viewer.dataSources.add(featuresDs.current);
    viewer.dataSources.add(calcDs.current);
    viewer.dataSources.add(overlayDs.current);
    viewer.dataSources.add(modelsDs.current);
    points.current = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
    viewerRef.current = viewer;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    handler.setInputAction((ev: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(ev.position);
      const id = picked?.id instanceof Cesium.Entity ? picked.id.id : null;
      if (typeof id === "string" && id.startsWith("f:")) useStore.getState().set({ selected: id.slice(2) });
      else if (typeof id === "string" && id.startsWith("b:")) useStore.getState().set({ selected: null });
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    // camera sync for split view
    const onMove = () => {
      if (!syncId || !hovering.current) return;
      const c = viewer.camera;
      cameraBus.dispatchEvent(
        new CustomEvent("cam", {
          detail: { from: syncId, position: c.positionWC.clone(), direction: c.directionWC.clone(), up: c.upWC.clone() },
        }),
      );
    };
    viewer.camera.percentageChanged = 0.001;
    const removeMove = viewer.camera.changed.addEventListener(onMove);
    const onCam = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (!syncId || d.from === syncId) return;
      viewer.camera.setView({ destination: d.position, orientation: { direction: d.direction, up: d.up } });
    };
    cameraBus.addEventListener("cam", onCam);
    return () => {
      removeMove();
      cameraBus.removeEventListener("cam", onCam);
      handler.destroy();
      viewer.destroy();
      viewerRef.current = null;
      pointById.current.clear();
    };
  }, [syncId]);

  // ------------------------------------------------------------------ basemap, imagery, terrain, 3D assets
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !site) return;
    viewer.imageryLayers.removeAll();
    const bm = basemapFor(basemap);
    if (bm.url) {
      viewer.imageryLayers.addImageryProvider(
        new Cesium.UrlTemplateImageryProvider({ url: bm.url, credit: new Cesium.Credit(bm.attribution), maximumLevel: bm.maxZoom }),
      );
    } else {
      viewer.imageryLayers.addImageryProvider(
        new Cesium.GridImageryProvider({ cells: 4, color: Cesium.Color.fromCssColorString("#ffffff").withAlpha(0.12), glowWidth: 0, backgroundColor: Cesium.Color.TRANSPARENT }),
      );
    }
    let cancelled = false;
    if (baseLayers.imagery) {
      for (const im of site.assets?.imagery ?? []) {
        Cesium.SingleTileImageryProvider.fromUrl(im.url, { rectangle: Cesium.Rectangle.fromDegrees(im.west, im.south, im.east, im.north), credit: im.attribution })
          .then((prov) => !cancelled && viewer.imageryLayers.addImageryProvider(prov))
          .catch(() => useStore.getState().toast("error", `Could not load orthophoto ${im.name}`));
      }
    }
    const turl = site.assets?.terrain_url;
    if (baseLayers.terrain && turl) {
      Cesium.CesiumTerrainProvider.fromUrl(turl)
        .then((tp) => !cancelled && (viewer.terrainProvider = tp))
        .catch(() => {
          useStore.getState().toast("error", "Could not load the quantized-mesh terrain; using the DEM heightmap");
          if (!cancelled) viewer.terrainProvider = terrain ? makeTerrain(terrain) : new Cesium.EllipsoidTerrainProvider();
        });
    } else {
      viewer.terrainProvider = baseLayers.terrain && terrain ? makeTerrain(terrain) : new Cesium.EllipsoidTerrainProvider();
    }
    const added: Cesium.Cesium3DTileset[] = [];
    if (baseLayers.tiles3d) {
      const urls = [...(site.assets?.tilesets ?? []).map((t) => t.url), ...(site.tileset_url ? [site.tileset_url] : [])];
      for (const u of urls) {
        Cesium.Cesium3DTileset.fromUrl(u)
          .then((ts) => {
            if (cancelled) return ts.destroy();
            added.push(viewer.scene.primitives.add(ts));
          })
          .catch(() => useStore.getState().toast("error", `Could not load 3D Tiles ${u}`));
      }
    }
    return () => {
      cancelled = true;
      for (const t of added) if (!viewer.isDestroyed()) viewer.scene.primitives.remove(t);
    };
  }, [site, terrain, basemap, baseLayers.imagery, baseLayers.terrain, baseLayers.tiles3d]);

  // glTF models placed from the data folder manifest
  useEffect(() => {
    const ds = modelsDs.current;
    if (!ds || !site) return;
    ds.entities.removeAll();
    if (!baseLayers.models) return;
    for (const m of site.assets?.models ?? []) {
      const pos = Cesium.Cartesian3.fromDegrees(m.lon, m.lat, m.height + (m.height === 0 ? sampleHeight(terrain, m.lon, m.lat) : 0));
      ds.entities.add({
        name: m.name,
        position: pos,
        orientation: Cesium.Transforms.headingPitchRollQuaternion(pos, new Cesium.HeadingPitchRoll(Cesium.Math.toRadians(m.heading_deg), 0, 0)) as any,
        model: { uri: m.url, scale: m.scale, minimumPixelSize: 24 },
      });
    }
  }, [site, terrain, baseLayers.models]);

  // fly to a searched / focused feature
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !focus) return;
    const f = features.find((x) => String(x.id) === focus.fid);
    if (!f) return;
    const flat = JSON.stringify(f.geometry.coordinates).match(/-?\d+\.?\d*(e-?\d+)?/g)?.map(Number) ?? [];
    let w = 180, s = 90, e = -180, n = -90;
    for (let i = 0; i + 1 < flat.length; i += 2) {
      w = Math.min(w, flat[i]); e = Math.max(e, flat[i]);
      s = Math.min(s, flat[i + 1]); n = Math.max(n, flat[i + 1]);
    }
    const c = Cesium.Cartesian3.fromDegrees((w + e) / 2, (s + n) / 2, sampleHeight(terrain, (w + e) / 2, (s + n) / 2));
    const r = Math.max(60, Cesium.Cartesian3.distance(Cesium.Cartesian3.fromDegrees(w, s), Cesium.Cartesian3.fromDegrees(e, n)));
    viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(c, r), { offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-45), r * 2.2), duration: 1.2 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  // area-calculation overlay (walkable / water / obstructions / barricades within the selected zone)
  useEffect(() => {
    const ds = calcDs.current;
    if (!ds) return;
    ds.entities.removeAll();
    if (!areaCalc) return;
    const colours: Record<string, Cesium.Color> = {
      walkable: Cesium.Color.fromCssColorString("#22c55e").withAlpha(0.55),
      water: Cesium.Color.fromCssColorString("#60a5fa").withAlpha(0.55),
      obstructions: Cesium.Color.fromCssColorString("#ef4444").withAlpha(0.7),
      barricades: Cesium.Color.fromCssColorString("#f97316").withAlpha(0.8),
    };
    for (const [k, g] of Object.entries(areaCalc.area.geometries ?? {})) {
      if (!g) continue;
      const polys: [number, number][][][] = g.type === "Polygon" ? [g.coordinates] : g.type === "MultiPolygon" ? g.coordinates : [];
      for (const rings of polys)
        ds.entities.add({
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(rings[0].flat()), rings.slice(1).map((r) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(r.flat())))),
            material: colours[k],
            classificationType: Cesium.ClassificationType.TERRAIN,
          },
        });
    }
  }, [areaCalc]);

  // fly to the site when it changes
  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !site || !features.length) return;
    let w = 180, s = 90, e = -180, n = -90;
    const core = features.filter((f) => !["river", "terrain_extent", "road"].includes(f.properties.pk_type));
    for (const f of core.length ? core : features) {
      const flat = JSON.stringify(f.geometry.coordinates).match(/-?\d+\.?\d*(e-?\d+)?/g)?.map(Number) ?? [];
      for (let i = 0; i + 1 < flat.length; i += 2) {
        w = Math.min(w, flat[i]); e = Math.max(e, flat[i]);
        s = Math.min(s, flat[i + 1]); n = Math.max(n, flat[i + 1]);
      }
    }
    const center = Cesium.Cartesian3.fromDegrees((w + e) / 2, (s + n) / 2, sampleHeight(terrain, (w + e) / 2, (s + n) / 2));
    const radius = Math.max(150, Cesium.Cartesian3.distance(Cesium.Cartesian3.fromDegrees(w, s), Cesium.Cartesian3.fromDegrees(e, n)) / 2);
    viewer.camera.flyToBoundingSphere(new Cesium.BoundingSphere(center, radius), {
      offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-40), radius * 1.9),
      duration: 0,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [site?.id, features.length > 0, terrain]);

  // ------------------------------------------------------------------ features
  useEffect(() => {
    const ds = featuresDs.current;
    if (!ds) return;
    ds.entities.suspendEvents();
    ds.entities.removeAll();
    const hide = hiddenTypes(hidden);
    const cfg = runData?.run.config;
    const disabled = new Set((cfg?.corridor_overrides ?? []).filter((o) => o.enabled === false).map((o) => o.corridor_id));
    const closedLater = new Set([...(cfg?.diversion?.close_corridors ?? []), ...(cfg?.evacuation?.close_corridors ?? [])]);
    const gateOff = new Set((cfg?.gate_overrides ?? []).filter((o) => o.enabled === false).map((o) => o.gate_id));
    const sorted = [...features].sort((a, b) => order(a) - order(b));
    for (const f of sorted) {
      const t = f.properties.pk_type;
      if (hide.has(t)) continue;
      const fid = String(f.id);
      const st = TYPE_STYLE[t] ?? { fill: "rgba(200,200,200,0.5)", stroke: "#999" };
      const isSel = fid === selected;
      const g = f.geometry;
      const id = `f:${fid}`;
      const name = f.properties.name ?? fid;
      try {
        if (g.type === "Polygon" || g.type === "MultiPolygon") {
          const polys: [number, number][][][] = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
          polys.forEach((rings, k) => {
            const outer = rings[0];
            const hierarchy = new Cesium.PolygonHierarchy(
              ringPositions(outer, null, null),
              rings.slice(1).map((r) => new Cesium.PolygonHierarchy(ringPositions(r, null, null))),
            );
            const fill = isSel ? Cesium.Color.YELLOW.withAlpha(0.7) : cssColor(st.fill);
            const topoBad = snapping.showTopology && f.properties.topology_valid === false;
            if (topoBad) {
              ds.entities.add({ polyline: { positions: Cesium.Cartesian3.fromDegreesArray(outer.flat()), width: 4, clampToGround: true, material: new Cesium.PolylineDashMaterialProperty({ color: Cesium.Color.RED }) } });
            }
            if (OBSTACLE_EXTRUDE.has(t) && baseLayers.buildings) {
              const base = Math.min(...outer.map(([x, y]) => sampleHeight(terrain, x, y)));
              ds.entities.add({
                id: k ? `${id}#${k}` : id,
                name,
                polygon: { hierarchy, height: base, extrudedHeight: base + Number(f.properties.height_m ?? 6), material: fill, outline: false },
              });
            } else {
              ds.entities.add({ id: k ? `${id}#${k}` : id, name, polygon: { hierarchy, material: fill, classificationType: Cesium.ClassificationType.TERRAIN } });
            }
          });
        } else if (g.type === "LineString") {
          const coords: [number, number][] = g.coordinates;
          if (t === "corridor" || t === "emergency_corridor") {
            let col = cssColor(st.fill);
            if (disabled.has(fid) || f.properties.enabled === false) col = Cesium.Color.RED.withAlpha(0.75);
            else if (closedLater.has(fid)) col = Cesium.Color.ORANGE.withAlpha(0.85);
            if (isSel) col = Cesium.Color.YELLOW.withAlpha(0.85);
            ds.entities.add({
              id,
              name,
              corridor: {
                positions: Cesium.Cartesian3.fromDegreesArray(coords.flat()),
                width: Number(f.properties.width_m ?? 4),
                material: col,
                cornerType: Cesium.CornerType.ROUNDED,
                classificationType: Cesium.ClassificationType.TERRAIN,
              },
            });
          } else if (t === "wall" || t === "barricade") {
            const base = coords.map(([x, y]) => sampleHeight(terrain, x, y));
            ds.entities.add({
              id,
              name,
              wall: {
                positions: Cesium.Cartesian3.fromDegreesArray(coords.flat()),
                minimumHeights: base,
                maximumHeights: base.map((b) => b + Number(f.properties.height_m ?? (t === "wall" ? 2.5 : 1.1))),
                material: isSel ? Cesium.Color.YELLOW : cssColor(st.fill),
              },
            });
          } else {
            ds.entities.add({
              id,
              name,
              polyline: { positions: Cesium.Cartesian3.fromDegreesArray(coords.flat()), width: 3, clampToGround: true, material: isSel ? Cesium.Color.YELLOW : cssColor(st.stroke) },
            });
          }
        } else if (g.type === "Point") {
          const [x, y] = g.coordinates as [number, number];
          let col = st.fill;
          if (t === "gate") col = f.properties.emergency_exit ? "#e67e22" : f.properties.role === "entry" ? "#27ae60" : f.properties.role === "exit" ? "#c0392b" : "#2980b9";
          if (gateOff.has(fid) || f.properties.enabled === false) col = "#7f8c8d";
          ds.entities.add({
            id,
            name,
            position: Cesium.Cartesian3.fromDegrees(x, y, sampleHeight(terrain, x, y) + 2),
            point: { pixelSize: isSel ? 14 : 10, color: cssColor(col), outlineColor: Cesium.Color.WHITE, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
            label: {
              text: `${POINT_SYMBOL[t] ?? "•"} ${t === "gate" ? name : ""}`.trim(),
              font: "11px sans-serif",
              fillColor: Cesium.Color.WHITE,
              showBackground: true,
              backgroundColor: cssColor(col, 0.8),
              pixelOffset: new Cesium.Cartesian2(0, -18),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
              scale: 0.9,
            },
          });
        }
      } catch {
        /* skip malformed geometry */
      }
    }
    ds.entities.resumeEvents();
  }, [features, hidden, selected, terrain, runData, baseLayers.buildings, snapping.showTopology]);

  // ------------------------------------------------------------------ static overlays (network, routes, bottlenecks, links)
  useEffect(() => {
    const ds = overlayDs.current;
    const viewer = viewerRef.current;
    if (!ds || !viewer) return;
    ds.entities.removeAll();
    linkEntities.current = [];
    if (densityPrim.current) {
      viewer.scene.primitives.remove(densityPrim.current);
      densityPrim.current = null;
      densityCells.current = [];
    }
    if (overlays.network && network) {
      for (const f of network.features) {
        if (f.properties.kind === "link") {
          ds.entities.add({
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(f.geometry.coordinates.flat()),
              width: 1.5,
              clampToGround: true,
              material: f.properties.emergency_only ? Cesium.Color.ORANGE : Cesium.Color.CYAN.withAlpha(0.8),
            },
          });
        } else {
          const [x, y] = f.geometry.coordinates;
          ds.entities.add({ position: Cesium.Cartesian3.fromDegrees(x, y, sampleHeight(terrain, x, y) + 1), point: { pixelSize: 5, color: Cesium.Color.CYAN, disableDepthTestDistance: Number.POSITIVE_INFINITY } });
        }
      }
    }
    if (overlays.routes && routeResult?.routes) {
      const cols = [Cesium.Color.LIME, Cesium.Color.MAGENTA, Cesium.Color.GOLD, Cesium.Color.AQUA, Cesium.Color.ORANGE];
      routeResult.routes.forEach((r: any, i: number) => {
        const lines = r.geometry.type === "LineString" ? [r.geometry.coordinates] : r.geometry.coordinates;
        for (const ln of lines)
          ds.entities.add({ polyline: { positions: Cesium.Cartesian3.fromDegreesArray(ln.flat()), width: 6 - i, clampToGround: true, material: cols[i % cols.length].withAlpha(0.85) } });
      });
    }
    if (runData) {
      const g = runData.grid.grid;
      if (overlays.density) {
        // one rectangle per walkable grid cell, draped 0.3 m above the terrain at the cell
        // centre; colours are per-instance attributes updated every frame (portable WebGL)
        const wa = runData.grid.walk_area;
        const dlon = (g.east - g.west) / g.nx;
        const dlat = (g.north - g.south) / g.ny;
        const minArea = 0.15 * g.cell_m * g.cell_m;
        const cells: number[] = [];
        const instances: Cesium.GeometryInstance[] = [];
        for (let i = 0; i < g.nx * g.ny; i++) {
          if (wa && wa[i] < minArea) continue;
          const iy = Math.floor(i / g.nx);
          const ix = i % g.nx;
          cells.push(i);
          instances.push(
            new Cesium.GeometryInstance({
              id: `d:${i}`,
              geometry: new Cesium.RectangleGeometry({
                rectangle: Cesium.Rectangle.fromDegrees(g.west + ix * dlon, g.south + iy * dlat, g.west + (ix + 1) * dlon, g.south + (iy + 1) * dlat),
                height: sampleHeight(terrain, g.west + (ix + 0.5) * dlon, g.south + (iy + 0.5) * dlat) + 0.3,
                vertexFormat: Cesium.PerInstanceColorAppearance.FLAT_VERTEX_FORMAT,
              }),
              attributes: {
                color: Cesium.ColorGeometryInstanceAttribute.fromColor(Cesium.Color.TRANSPARENT),
                show: new Cesium.ShowGeometryInstanceAttribute(false),
              },
            }),
          );
        }
        if (instances.length) {
          densityPrim.current = viewer.scene.primitives.add(
            new Cesium.Primitive({
              geometryInstances: instances,
              appearance: new Cesium.PerInstanceColorAppearance({ flat: true, translucent: true }),
              asynchronous: false,
            }),
          );
          densityCells.current = cells;
          if (import.meta.env.DEV) (window as any).__pkDensity = { prim: densityPrim.current, cells };
          // repaint once the primitive has been built
          const iv = window.setInterval(() => {
            if (!densityPrim.current || densityPrim.current.ready) {
              window.clearInterval(iv);
              setPrimTick((x) => x + 1);
            }
          }, 250);
        }
      }
      if (overlays.flows && runData.links) {
        // two directions of a corridor share geometry; show the summed density
        const groups = new Map<string, { coords: [number, number][]; members: number[]; width: number }>();
        runData.links.links.forEach((lk, i) => {
          const a = lk.coords[0].join(",");
          const b = lk.coords[lk.coords.length - 1].join(",");
          const key = a < b ? `${a}|${b}` : `${b}|${a}`;
          const gr = groups.get(key);
          if (gr) gr.members.push(i);
          else groups.set(key, { coords: lk.coords, members: [i], width: lk.width });
        });
        for (const gr of groups.values()) {
          const e = ds.entities.add({
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(gr.coords.flat()),
              width: Math.min(14, Math.max(3, gr.width * 0.9)),
              clampToGround: true,
              material: Cesium.Color.GRAY.withAlpha(0.6),
            },
          });
          linkEntities.current.push({ entity: e, members: gr.members });
        }
      }
      if (overlays.bottlenecks) {
        runData.analysis.bottlenecks.slice(0, 20).forEach((b, i) => {
          ds.entities.add({
            id: `b:${i}`,
            position: Cesium.Cartesian3.fromDegrees(b.lon, b.lat, sampleHeight(terrain, b.lon, b.lat) + 4),
            point: { pixelSize: 16, color: Cesium.Color.RED.withAlpha(0.35), outlineColor: Cesium.Color.RED, outlineWidth: 2, disableDepthTestDistance: Number.POSITIVE_INFINITY },
            label: {
              text: `B${i + 1} ${b.max_density_ppm2} p/m²${b.unresolved ? " (unresolved)" : ""}`,
              font: "11px sans-serif",
              showBackground: true,
              backgroundColor: Cesium.Color.fromCssColorString("#7b1010").withAlpha(0.85),
              pixelOffset: new Cesium.Cartesian2(0, -22),
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          });
        });
      }
    }
    if (!runData || !overlays.agents) {
      points.current?.removeAll();
      pointById.current.clear();
    }
  }, [runData, overlays, network, routeResult, terrain]);

  // ------------------------------------------------------------------ per-frame update
  useEffect(() => {
    if (timeLabel.current) {
      timeLabel.current.textContent = runData ? `t = ${fmtTime(time)}` : "";
    }
    if (!runData) return;
    // agents
    if (overlays.agents && runData.agents && points.current) {
      const frames = runData.agents;
      const fi = frameIndex(frames.map((f) => f.t), time);
      const fr = frames[fi];
      const seen = new Set<number>();
      const coll = points.current;
      if (fr) {
        for (let i = 0; i < fr.ids.length; i++) {
          const id = fr.ids[i];
          seen.add(id);
          const pos = Cesium.Cartesian3.fromDegrees(fr.lon[i], fr.lat[i], sampleHeight(terrain, fr.lon[i], fr.lat[i]) + 0.9);
          let p = pointById.current.get(id);
          if (!p) {
            p = coll.add({ position: pos, pixelSize: 4, color: Cesium.Color.fromCssColorString("#ff6f00"), outlineColor: Cesium.Color.BLACK, outlineWidth: 0.5 });
            pointById.current.set(id, p);
          } else {
            p.position = pos;
            p.show = true;
          }
        }
      }
      for (const [id, p] of pointById.current) if (!seen.has(id)) p.show = false;
    }
    // density grid
    const prim = densityPrim.current;
    if (prim && prim.ready && overlays.density) {
      const g = runData.grid;
      const dense = denseFrame(g, g.frames[frameIndex(g.times, time)]);
      const cols = BAND_COLOURS.map((c) => Cesium.Color.fromCssColorString(c).withAlpha(0.85));
      for (const i of densityCells.current) {
        const v = dense[i];
        const attrs = prim.getGeometryInstanceAttributes(`d:${i}`);
        if (!attrs) continue;
        const show = v >= 0.05;
        attrs.show = Cesium.ShowGeometryInstanceAttribute.toValue(show, attrs.show);
        if (show) attrs.color = Cesium.ColorGeometryInstanceAttribute.toValue(cols[bandIndex(v, bands)], attrs.color);
      }
    }
    // macroscopic link densities
    if (runData.links && linkEntities.current.length) {
      const L = runData.links;
      const fi = frameIndex(L.times, time);
      const fr = L.frames[fi] ?? [];
      for (const le of linkEntities.current) {
        const k = le.members.reduce((a, i) => a + (fr[i] ?? 0), 0);
        const col = k < 0.02 ? Cesium.Color.GRAY.withAlpha(0.5) : Cesium.Color.fromCssColorString(BAND_COLOURS[bandIndex(k, bands)]);
        le.entity.polyline!.material = new Cesium.ColorMaterialProperty(col);
      }
    }
  }, [time, runData, overlays, bands, terrain, primTick]);

  return (
    <div
      className="cesium-wrap"
      onMouseEnter={() => (hovering.current = true)}
      onMouseLeave={() => (hovering.current = false)}
      onDoubleClick={() => set({ selected: null })}
    >
      <div ref={container} className="cesium-container" />
      <div className="view-badges">
        {title && <span className="badge dark">{title}</span>}
        {runData && <span className="badge sim">{runData.analysis.engine.method_type === "agent_based" ? "Agent-based simulation" : "Macroscopic flow estimate"} · SIMULATED</span>}
        <span className="badge dark" ref={timeLabel} />
      </div>
    </div>
  );
}

function order(f: Feature): number {
  const t = f.properties.pk_type;
  if (t === "river") return 0;
  if (["bathing_area", "ghat", "plaza", "holding_area", "parking", "bus_terminal", "transit_hub", "assembly_point", "zone"].includes(t)) return 1;
  if (t === "corridor" || t === "emergency_corridor") return 2;
  return 3;
}

/** Density colour scale shared by the 3D view, 2D map and legends. Breaks come
 * from the active (configurable) threshold profile. */
export const BAND_COLOURS = ["#2c7bb6", "#00a6ca", "#00ccbc", "#90eb9d", "#ffff8c", "#f9d057", "#f29e2e", "#d7191c"];

export function bandIndex(v: number, bands: number[]): number {
  let i = 0;
  while (i < bands.length && v > bands[i]) i++;
  return Math.min(i, BAND_COLOURS.length - 1);
}

export function densityColour(v: number, bands: number[]): string {
  return BAND_COLOURS[bandIndex(v, bands)];
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

export function bandLabels(bands: number[]): string[] {
  const out = [`≤ ${bands[0]}`];
  for (let i = 1; i < bands.length; i++) out.push(`${bands[i - 1]}–${bands[i]}`);
  out.push(`> ${bands[bands.length - 1]}`);
  return out;
}

/** Map/feature styling per feature type (fill, stroke). */
export const TYPE_STYLE: Record<string, { fill: string; stroke: string }> = {
  river: { fill: "rgba(70,130,200,0.45)", stroke: "#3a6ea5" },
  bathing_area: { fill: "rgba(90,170,230,0.45)", stroke: "#2b7bb9" },
  ghat: { fill: "rgba(205,170,125,0.6)", stroke: "#8b6b3e" },
  steps: { fill: "rgba(205,170,125,0.6)", stroke: "#8b6b3e" },
  ramp: { fill: "rgba(200,190,150,0.6)", stroke: "#8b7b4e" },
  temple: { fill: "rgba(230,120,40,0.8)", stroke: "#a0501a" },
  building: { fill: "rgba(150,150,160,0.85)", stroke: "#555" },
  wall: { fill: "#444", stroke: "#444" },
  barricade: { fill: "#c0392b", stroke: "#c0392b" },
  obstacle: { fill: "rgba(90,90,90,0.8)", stroke: "#333" },
  road: { fill: "#999", stroke: "#888" },
  corridor: { fill: "rgba(240,240,240,0.9)", stroke: "#b8b8b8" },
  emergency_corridor: { fill: "rgba(255,200,200,0.9)", stroke: "#e74c3c" },
  queue_lane: { fill: "rgba(255,230,150,0.6)", stroke: "#c9a227" },
  plaza: { fill: "rgba(230,230,220,0.6)", stroke: "#aaa" },
  gate: { fill: "#27ae60", stroke: "#1e8449" },
  holding_area: { fill: "rgba(155,89,182,0.25)", stroke: "#8e44ad" },
  assembly_point: { fill: "rgba(46,204,113,0.3)", stroke: "#1e8449" },
  transit_hub: { fill: "rgba(52,73,94,0.25)", stroke: "#34495e" },
  bus_terminal: { fill: "rgba(52,73,94,0.25)", stroke: "#34495e" },
  parking: { fill: "rgba(127,140,141,0.25)", stroke: "#7f8c8d" },
  hospital: { fill: "#e74c3c", stroke: "#fff" },
  first_aid: { fill: "#e74c3c", stroke: "#fff" },
  control_point: { fill: "#2c3e50", stroke: "#fff" },
  speaker: { fill: "#f39c12", stroke: "#fff" },
  zone: { fill: "rgba(0,0,0,0)", stroke: "#16a085" },
  terrain_extent: { fill: "rgba(0,0,0,0)", stroke: "#999" },
};

export const POINT_SYMBOL: Record<string, string> = {
  gate: "G",
  hospital: "H",
  first_aid: "+",
  control_point: "C",
  speaker: "S",
  assembly_point: "A",
};

export const LAYER_GROUPS: { key: string; label: string; types: string[] }[] = [
  { key: "water", label: "River & bathing", types: ["river", "bathing_area"] },
  { key: "ghats", label: "Ghats, steps, ramps", types: ["ghat", "steps", "ramp"] },
  { key: "built", label: "Temples, buildings, walls", types: ["temple", "building", "wall", "obstacle"] },
  { key: "movement", label: "Corridors & roads", types: ["corridor", "road", "queue_lane", "plaza"] },
  { key: "emergency", label: "Emergency corridors", types: ["emergency_corridor"] },
  { key: "control", label: "Gates & barricades", types: ["gate", "barricade"] },
  { key: "holding", label: "Holding & assembly", types: ["holding_area", "assembly_point"] },
  { key: "transport", label: "Transit, bus, parking", types: ["transit_hub", "bus_terminal", "parking"] },
  { key: "services", label: "Hospitals, first aid, control, PA", types: ["hospital", "first_aid", "control_point", "speaker"] },
  { key: "zones", label: "Analysis zones", types: ["zone", "terrain_extent"] },
];

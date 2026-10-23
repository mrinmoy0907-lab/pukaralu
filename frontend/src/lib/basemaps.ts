/** Basemaps shown behind the Digital Twin (2D and 3D). Check each provider's
 * terms before production use; a self-hosted or licensed tile service can be
 * configured with VITE_BASEMAP_URL / VITE_BASEMAP_ATTRIBUTION. */
export interface Basemap {
  key: string;
  label: string;
  url: string | null; // XYZ template ({z}/{x}/{y}); null = no basemap
  attribution: string;
  real: boolean; // shows the real world (vs. a neutral grid)
  maxZoom: number;
}

const custom = (import.meta.env?.VITE_BASEMAP_URL as string | undefined) || "";

export const BASEMAPS: Basemap[] = [
  { key: "osm", label: "OpenStreetMap streets", url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "© OpenStreetMap contributors", real: true, maxZoom: 19 },
  {
    key: "satellite",
    label: "Satellite imagery (Esri World Imagery)",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    real: true,
    maxZoom: 19,
  },
  { key: "light", label: "Light (CARTO Positron)", url: "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", attribution: "© OpenStreetMap contributors © CARTO", real: true, maxZoom: 20 },
  { key: "dark", label: "Dark (CARTO Dark Matter)", url: "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", attribution: "© OpenStreetMap contributors © CARTO", real: true, maxZoom: 20 },
  ...(custom
    ? [{ key: "custom", label: "Custom tiles", url: custom, attribution: (import.meta.env?.VITE_BASEMAP_ATTRIBUTION as string) || "Custom basemap", real: true, maxZoom: 22 }]
    : []),
  { key: "grid", label: "None (neutral grid)", url: null, attribution: "", real: false, maxZoom: 22 },
];

export function basemapFor(key: string | null | undefined): Basemap {
  return BASEMAPS.find((b) => b.key === key) ?? BASEMAPS[0];
}

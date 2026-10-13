import type { Terrain } from "../types";

/** Bilinear sample of the site heightmap (row 0 = north). Returns min height outside the extent. */
export function sampleHeight(t: Terrain | null, lon: number, lat: number): number {
  if (!t) return 0;
  if (lon < t.west || lon > t.east || lat < t.south || lat > t.north) return t.min;
  const fx = ((lon - t.west) / (t.east - t.west)) * (t.width - 1);
  const fy = ((t.north - lat) / (t.north - t.south)) * (t.height - 1);
  const x0 = Math.floor(fx);
  const y0 = Math.floor(fy);
  const x1 = Math.min(x0 + 1, t.width - 1);
  const y1 = Math.min(y0 + 1, t.height - 1);
  const ax = fx - x0;
  const ay = fy - y0;
  const h = t.heights;
  return (
    h[y0][x0] * (1 - ax) * (1 - ay) + h[y0][x1] * ax * (1 - ay) + h[y1][x0] * (1 - ax) * ay + h[y1][x1] * ax * ay
  );
}

/** Heights for a terrain tile (row 0 = north), used by Cesium's CustomHeightmapTerrainProvider. */
export function tileHeights(t: Terrain, west: number, south: number, east: number, north: number, size: number): Float32Array {
  const out = new Float32Array(size * size);
  for (let r = 0; r < size; r++) {
    const lat = north - ((north - south) * r) / (size - 1);
    for (let c = 0; c < size; c++) {
      const lon = west + ((east - west) * c) / (size - 1);
      out[r * size + c] = sampleHeight(t, lon, lat);
    }
  }
  return out;
}

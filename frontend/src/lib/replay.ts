import type { GridDoc } from "../types";

/** Index of the frame whose time is closest to (and not after) t. Binary search. */
export function frameIndex(times: number[], t: number): number {
  if (!times.length) return -1;
  if (t <= times[0]) return 0;
  if (t >= times[times.length - 1]) return times.length - 1;
  let lo = 0;
  let hi = times.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Expand a sparse density frame [indices, values] to a dense row-major array (row 0 = south). */
export function denseFrame(grid: GridDoc, frame: [number[], number[]] | undefined): Float32Array {
  const out = new Float32Array(grid.grid.nx * grid.grid.ny);
  if (!frame) return out;
  const [idx, vals] = frame;
  for (let i = 0; i < idx.length; i++) out[idx[i]] = vals[i];
  return out;
}

/** Decimation so that at most `maxFrames` frames are downloaded. */
export function decimation(nFrames: number, maxFrames: number): number {
  return Math.max(1, Math.ceil(nFrames / maxFrames));
}

export function fmtTime(s: number | null | undefined): string {
  if (s === null || s === undefined || Number.isNaN(s)) return "–";
  const total = Math.round(s);
  const m = Math.floor(total / 60);
  const sec = total - m * 60;
  return m > 0 ? `${m}m ${String(sec).padStart(2, "0")}s` : `${sec}s`;
}

export function fmtNum(v: number | null | undefined, nd = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toLocaleString(undefined, { maximumFractionDigits: nd });
}

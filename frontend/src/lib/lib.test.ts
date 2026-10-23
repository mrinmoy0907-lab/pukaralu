import { describe, expect, it } from "vitest";
import { bandIndex, bandLabels, densityColour, BAND_COLOURS } from "./colors";
import { decimation, denseFrame, fmtTime, frameIndex } from "./replay";
import { emptyConfig, expectedPopulation, precheck } from "./scenario";
import { sampleHeight, tileHeights } from "./terrain";
import type { Feature, GridDoc, Terrain } from "../types";
import { errorDetails } from "../api";
import { basemapFor, BASEMAPS } from "./basemaps";

describe("replay", () => {
  it("finds the frame at or before t", () => {
    const t = [0, 1, 2, 3, 10];
    expect(frameIndex(t, -5)).toBe(0);
    expect(frameIndex(t, 2.5)).toBe(2);
    expect(frameIndex(t, 9.99)).toBe(3);
    expect(frameIndex(t, 50)).toBe(4);
    expect(frameIndex([], 1)).toBe(-1);
  });
  it("expands sparse density frames", () => {
    const g = { grid: { nx: 3, ny: 2 } } as GridDoc;
    expect(Array.from(denseFrame(g, [[1, 5], [0.5, 2]]))).toEqual([0, 0.5, 0, 0, 0, 2]);
  });
  it("decimates and formats", () => {
    expect(decimation(1800, 900)).toBe(2);
    expect(decimation(10, 900)).toBe(1);
    expect(fmtTime(125)).toBe("2m 05s");
    expect(fmtTime(null)).toBe("–");
  });
});

describe("density colours", () => {
  const bands = [0.5, 1, 2, 4];
  it("maps values to bands from the configurable profile", () => {
    expect(bandIndex(0.2, bands)).toBe(0);
    expect(bandIndex(0.5, bands)).toBe(0);
    expect(bandIndex(1.5, bands)).toBe(2);
    expect(bandIndex(99, bands)).toBe(4);
    expect(densityColour(99, bands)).toBe(BAND_COLOURS[4]);
    expect(bandLabels(bands)).toHaveLength(5);
  });
});

describe("terrain sampling", () => {
  const t: Terrain = { west: 0, east: 1, south: 0, north: 1, width: 2, height: 2, heights: [[10, 20], [0, 10]], min: 0, max: 20 };
  it("interpolates bilinearly (row 0 = north)", () => {
    expect(sampleHeight(t, 0, 1)).toBeCloseTo(10);
    expect(sampleHeight(t, 1, 0)).toBeCloseTo(10);
    expect(sampleHeight(t, 0.5, 0.5)).toBeCloseTo(10);
    expect(sampleHeight(t, 1, 1)).toBeCloseTo(20);
    expect(sampleHeight(t, 5, 5)).toBe(0);
    expect(sampleHeight(null, 0, 0)).toBe(0);
  });
  it("builds tile heightmaps", () => {
    const h = tileHeights(t, 0, 0, 1, 1, 3);
    expect(h.length).toBe(9);
    expect(h[0]).toBeCloseTo(10);
  });
});

describe("scenario pre-checks", () => {
  const features = [
    { type: "Feature", id: "g1", geometry: { type: "Point", coordinates: [0, 0] }, properties: { pk_type: "gate" } },
    { type: "Feature", id: "h1", geometry: { type: "Polygon", coordinates: [] }, properties: { pk_type: "holding_area" } },
    { type: "Feature", id: "b1", geometry: { type: "Polygon", coordinates: [] }, properties: { pk_type: "bathing_area" } },
  ] as Feature[];
  it("accepts a consistent configuration", () => {
    const c = emptyConfig("x");
    c.demand = [{ gate_id: "g1", rate_per_min: 60, start_s: 0, end_s: null }];
    c.destinations = [{ target_id: "b1", share: 1, dwell_s: 60 }];
    c.holding_stops = [{ holding_id: "h1", share: 0.5, dwell_s: 60 }];
    expect(precheck(c, features)).toEqual([]);
    expect(expectedPopulation(c)).toBe(900);
  });
  it("reports problems", () => {
    const c = emptyConfig("");
    c.demand = [{ gate_id: "b1", rate_per_min: 60, start_s: 0, end_s: null }];
    c.holding_stops = [{ holding_id: "h1", share: 0.8, dwell_s: 1 }, { holding_id: "b1", share: 0.5, dwell_s: 1 }];
    c.time_step_s = 1;
    const errs = precheck(c, features).join(" | ");
    expect(errs).toContain("name is required");
    expect(errs).toContain("not a gate");
    expect(errs).toContain("≤ 1");
    expect(errs).toContain("not a holding area");
    expect(errs).toContain("time step");
    expect(errs).toContain("at least one destination");
  });
});

describe("API error formatting", () => {
  it("handles FastAPI shapes", () => {
    expect(errorDetails({ detail: "boom" })).toEqual(["boom"]);
    expect(errorDetails({ detail: { errors: ["a", "b"] } })).toEqual(["a", "b"]);
    expect(errorDetails({ detail: [{ loc: ["body", "x"], msg: "bad" }] })).toEqual(["x: bad"]);
  });
});

describe("basemaps", () => {
  it("falls back to the first basemap and offers a neutral option", () => {
    expect(basemapFor("nope").key).toBe(BASEMAPS[0].key);
    expect(basemapFor("satellite").real).toBe(true);
    expect(basemapFor("grid").url).toBeNull();
  });
});

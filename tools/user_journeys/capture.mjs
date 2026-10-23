// Captures the screenshots for docs/user-journeys.pdf by driving the real application.
//
//   1. start the API (port 8000) and the Vite dev server (port 5173) on a fresh database
//   2. node tools/user_journeys/capture.mjs        (from the repository root; needs `npx playwright install chromium`)
//   3. node tools/user_journeys/build_pdf.mjs
//
// The journeys use the bundled SIM DATA sites. Every screenshot shows simulated data.
import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(join(dirname(fileURLToPath(import.meta.url)), "../../frontend/package.json"));
const { chromium } = require("playwright");

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const UI = process.env.PK_UI ?? "http://127.0.0.1:5173";
const API = process.env.PK_API ?? "http://127.0.0.1:8000";
const OUT = join(ROOT, "docs", "journeys");
mkdirSync(join(OUT, "img"), { recursive: true });

const api = async (method, path, body) => {
  const r = await fetch(API + path, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`);
  return r.status === 204 ? null : r.json();
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ prepare data and runs
const sites = await api("GET", "/api/sites");
const real = sites.find((s) => s.name.startsWith("SIM DATA layout on real map"));
const offshore = sites.find((s) => s.name.startsWith("SYNTHETIC demonstration"));
const scen = await api("GET", `/api/sites/${real.id}/scenarios`);
const byPreset = Object.fromEntries(scen.map((s) => [s.preset, s]));
const want = [
  ["normal", "jupedsim"],
  ["peak_bathing", "jupedsim"],
  ["holding_overcrowded", "macro_ctm"],
  ["blocked_corridor", "macro_ctm"],
  ["evacuation", "macro_ctm"],
];
const runs = {};
const existing = await api("GET", `/api/runs?site_id=${real.id}`);
for (const [preset, engine] of want) {
  const done = existing.find((r) => r.scenario_id === byPreset[preset].id && r.engine === engine && r.status === "completed");
  runs[preset] = done ?? (await api("POST", `/api/scenarios/${byPreset[preset].id}/runs`, { engine }));
}
console.log("waiting for simulations ...");
for (;;) {
  const st = await Promise.all(Object.values(runs).map((r) => api("GET", `/api/runs/${r.id}`)));
  if (st.every((r) => ["completed", "failed", "cancelled"].includes(r.status))) {
    st.forEach((r) => r.status !== "completed" && console.warn("run not completed:", r.name, r.error));
    break;
  }
  await sleep(5000);
}

// make the script re-runnable: remove the zone drawn by a previous capture
for (const f of (await api("GET", `/api/sites/${real.id}/features`)).features)
  if (f.properties.name === "Main Ghat Sector") await api("DELETE", `/api/sites/${real.id}/features/${encodeURIComponent(f.id)}`);
const feats = (await api("GET", `/api/sites/${real.id}/features`)).features;
const bbox = (fid) => {
  const f = feats.find((x) => x.id === fid);
  const c = JSON.stringify(f.geometry.coordinates).match(/-?\d+\.?\d*/g).map(Number);
  let w = 999, s = 999, e = -999, n = -999;
  for (let i = 0; i < c.length; i += 2) {
    w = Math.min(w, c[i]); e = Math.max(e, c[i]); s = Math.min(s, c[i + 1]); n = Math.max(n, c[i + 1]);
  }
  return { w, s, e, n };
};

// ------------------------------------------------------------------ browser helpers
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
page.on("pageerror", (e) => console.warn("pageerror", e.message));
page.setDefaultTimeout(60000);
const journeys = [];
let cur = null;
let n = 0;

async function goto(q, wait = 3500) {
  // "load", not "networkidle": map tiles may be retried forever when offline
  await page.goto(`${UI}/?${q}`, { waitUntil: "load", timeout: 120000 });
  await page.waitForSelector(".navrail", { timeout: 60000 });
  if (q.includes("run=")) await page.waitForSelector(".kpis", { timeout: 180000 });
  await page.waitForTimeout(wait);
}
async function shot(title, caption, focus) {
  n += 1;
  const file = `${cur.id}_${cur.steps.length + 1}.jpg`;
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(OUT, "img", file), type: "jpeg", quality: 78, timeout: 180000 });
  const step = { title, caption, img: `img/${file}` };
  // close-up of the panel where the action happens (readable in print)
  if (focus) {
    const el = page.locator(focus).first();
    if (await el.count()) {
      const d = file.replace(".jpg", "_d.jpg");
      await el.screenshot({ path: join(OUT, "img", d), type: "jpeg", quality: 85, timeout: 60000 });
      step.detail = `img/${d}`;
    }
  }
  cur.steps.push(step);
  console.log(`  ${cur.id} step ${cur.steps.length}: ${title}`);
}
function journey(id, title, roles, goal) {
  cur = { id, title, roles, goal, steps: [] };
  journeys.push(cur);
  console.log(id, title);
}
async function mapClick(lon, lat, dbl = false) {
  const px = await page.evaluate(([x, y]) => window.__pkToPixel(x, y), [lon, lat]);
  const box = await page.locator(".plan-map").boundingBox();
  if (dbl) await page.mouse.dblclick(box.x + px[0], box.y + px[1]);
  else await page.mouse.click(box.x + px[0], box.y + px[1]);
  await page.waitForTimeout(300);
}
async function setTime(t) {
  await page.evaluate((tt) => {
    const r = document.querySelector(".scrub input");
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    set.call(r, String(tt));
    r.dispatchEvent(new Event("input", { bubbles: true }));
  }, t);
  await page.waitForTimeout(2500);
}
const btn = (name) => page.getByRole("button", { name, exact: false }).first();
const openSection = async (title) => {
  const s = page.locator(`details.section:has(> summary:has-text("${title}"))`).first();
  // force: software WebGL can starve animation frames, which Playwright's stability check waits for
  if ((await s.getAttribute("open")) === null) await s.locator("summary").click({ force: true });
  await s.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
};

const S = real.id;
const M_LAT = 1 / 110540;
const M_LON = 1 / (111320 * Math.cos((real.origin[1] * Math.PI) / 180));
const [olon, olat] = real.origin;

// ------------------------------------------------------------------ P-01
journey("P-01", "Zone and walkable-area setup", ["R7", "R3"], "Define operational zones and calculate usable crowd area (excluding water, stalls and barricades).");
await goto(`site=${S}&tab=zones&view=2d`);
await btn("Layers").click();
await shot("Turn on layers", "R7 opens Layers: operational layers (zones, walkable areas, obstructions, barricades, gates) and base layers (real map, ortho imagery, 3D buildings, DTM).", '.layers-menu');
await page.keyboard.press("Escape");
await page.mouse.click(900, 600);
await btn("Draw Zone").click();
const z = [
  [olon - 20 * M_LON, olat - 80 * M_LAT],
  [olon + 54 * M_LON, olat - 80 * M_LAT],
  [olon + 54 * M_LON, olat + 30 * M_LAT],
  [olon - 20 * M_LON, olat + 30 * M_LAT],
];
await mapClick(...z[0]);
await mapClick(...z[1]);
await mapClick(...z[2]);
await shot("Draw zone boundary", "R7 clicks Draw Zone and traces the boundary on the map; snapping to corridors and the river edge is on, overlaps are prevented.", '.snapping');
await mapClick(...z[3], true);
await page.getByLabel("Zone name *", { exact: true }).fill("Main Ghat Sector");
await page.getByLabel("Owner department *", { exact: true }).selectOption("Mela Administration");
await page.getByLabel("Type", { exact: true }).selectOption("ghat");
await page.getByLabel("Valid from", { exact: true }).fill("2026-10-10T00:00");
await page.getByLabel("Valid to", { exact: true }).fill("2026-10-31T23:59");
await page.getByLabel("Description", { exact: true }).fill("Main ghat sector used for routine bathing and rituals (SIM DATA example).");
await shot("Fill zone properties", "R7 fills name, parent zone, type, owner department, validity dates and description.", '.side-panel');
await page.locator(".side-panel").getByRole("button", { name: "Save" }).click();
await page.waitForSelector(".area-card", { timeout: 30000 });
await shot("Recalculate walkable area", "Net walkable area = gross area − water − obstructions (stalls) − barricades + DTM step surface; topology is checked.", '.area-card');
await page.locator(".role-select").selectOption("R3");
for (const name of ["Main Ghat Sector", "Holding Area West", "Holding Area East", "Ghat front plaza"]) {
  await page.locator(".register-table tr", { hasText: name }).first().locator("input[type=checkbox]").check();
}
await page.getByLabel("Approved by *", { exact: true }).fill("Zone in-charge (R3)");
await page.getByLabel("Approval remarks", { exact: true }).fill("Zone boundaries and owner departments verified.");
await page.getByLabel("Effective from", { exact: true }).fill("2026-10-10");
await page.getByLabel("Effective to", { exact: true }).fill("2026-10-31");
await shot("Review and confirm", "R3 reviews the zone register and owner departments, sets the effective period and clicks Confirm & Activate.", '.approval');
await btn("Confirm & Activate").click();
await page.waitForTimeout(2500);
await shot("Zones active", "The selected zones are active; the approval record (approver, remarks, period) is stored with each zone.", '.register-table');

// ------------------------------------------------------------------ P-02
journey("P-02", "Load surveyed GIS, DTM and 3D models", ["R7", "R1"], "Copy surveyed vectors, DTM/DEM, 3D Tiles, glTF models and orthophotos into data/sites/<site>/ and load them.");
await goto(`site=${offshore.id}&tab=data&view=2d`);
await shot("Data folder", "Each site has a folder under data/sites with vector/, dem/, terrain/, tiles3d/, models/, imagery/ and an optional site.json manifest.", '.sheet details.section');
await btn("Scan data folder").click();
await page.waitForTimeout(4000);
await shot("Scan data folder", "Scan data folder (or restart, or scan_data_windows.bat) imports new and changed files; unchanged files are skipped.", '.sheet details.section');
await openSection("Site & data provenance");
await page.locator("details.section:has(> summary:has-text(\"Site & data provenance\"))").scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
await shot("Provenance and licences", "Every dataset is recorded with licence, attribution, synthetic/surveyed flags, source CRS and SHA-256.", 'details.section:has(> summary:has-text("Site & data provenance"))');
await goto(`site=${offshore.id}&tab=overview&view=3d`, 6000);
await btn("Layers").click();
await shot("Verify in 3D", "The DTM drives the 3D terrain; Layers toggles ortho imagery, 3D buildings, 3D Tiles, glTF models and terrain.", '.layers-menu');

// ------------------------------------------------------------------ P-03
journey("P-03", "Corridors, gates and network check", ["R7"], "Draw pedestrian corridors and gates and verify that the walkable network is connected.");
await goto(`site=${S}&tab=workbench&view=2d`);
await btn("More").click();
await shot("Choose a feature type", "Planning Workbench: Select, Draw Zone, Draw Obstruction, Add Gate, Edit, Delete; More… lists corridors, holding areas, ghats, barricades and all other types.", '.more-menu');
await page.locator(".more-menu button", { hasText: "Pedestrian corridor" }).click();
const h = bbox("hold_e");
await mapClick(h.e + 2 * M_LON, (h.s + h.n) / 2);
await mapClick(h.e + 60 * M_LON, (h.s + h.n) / 2, true);
await page.getByLabel("Name *", { exact: true }).fill("New link to east road");
await page.getByLabel("Width", { exact: true }).fill("5");
await shot("Draw corridor and set attributes", "A corridor centre-line is drawn; width, direction (one-way), surface (stairs/ramps) and emergency-only are set as attributes.", '.side-panel');
await page.locator(".side-panel").getByRole("button", { name: "Discard" }).click();
await page.getByLabel("Pedestrian network (nodes/links)", { exact: true }).check();
await page.waitForTimeout(2500);
await shot("Show the pedestrian network", "The network derived from corridors, gates and areas is shown with node/link statistics and connectivity warnings.", 'details.section:has(> summary:has-text("Simulation overlays"))');
await page.locator(".search input").fill("Temple street");
await page.locator(".search-results button").first().click();
await page.waitForTimeout(1500);
await shot("Inspect and edit", "Search finds a feature and flies to it; the inspector shows capacity (1.22 p/(m·s) × width) and editable attributes.", '.inspector');

// ------------------------------------------------------------------ P-04
journey("P-04", "Alternative routes and diversions", ["R7"], "Compare alternative routes between gates and areas, with closures and route bottleneck capacities.");
await goto(`site=${S}&tab=workbench&view=2d`);
await page.getByLabel("From", { exact: true }).selectOption("g_bus");
await page.getByLabel("To", { exact: true }).selectOption("bath_main");
await btn("Find routes").click();
await page.waitForTimeout(2000);
await shot("Compare routes", "Yen's k-shortest routes from the bus terminal to the bathing area: length, free-flow time and bottleneck capacity.", 'details.section:has(> summary:has-text("Route explorer"))');
await page.locator(".multicheck label", { hasText: "Temple street" }).locator("input").check();
await btn("Find routes").click();
await page.waitForTimeout(2000);
await shot("Route with a closure", "With Temple street treated as closed, the alternatives use the holding-area approaches.", 'details.section:has(> summary:has-text("Route explorer"))');

// ------------------------------------------------------------------ P-05
journey("P-05", "Holding-area capacity", ["R7", "R5"], "Estimate holding-area occupancy, time to reach the limit and alternatives.");
await goto(`site=${S}&run=${runs.holding_overcrowded.id}&tab=results&view=2d&t=1000`, 5000);
await setTime(1000);
await shot("Overcrowded holding area", "Macroscopic run of the overcrowded-holding preset: density on the map, KPIs and time series.", '.kpis');
await openSection("Holding-area capacity");
await shot("Capacity, time to limit, suggestions", "Usable area excludes obstructions; limit = min(operational capacity, density limit × usable area); suggestions name alternative holding areas.", 'details.section:has(> summary:has-text("Holding-area capacity"))');

// ------------------------------------------------------------------ P-06
journey("P-06", "Scenario setup", ["R7"], "Create a scenario from a preset and edit arrivals, destinations, behaviour and circulation plan.");
await goto(`site=${S}&tab=scenarios&view=3d`, 5000);
await shot("Scenario list and presets", "Ten presets are generated from the site's own features; every value is editable.", 'details.section:has(> summary:has-text("Scenarios"))');
await page.locator(".sheet select").first().selectOption("peak_bathing");
await page.waitForTimeout(1000);
await shot("Edit parameters", "Duration, time step, method, arrivals by gate, entry restrictions, destinations, holding stops, corridors and gates, diversion, evacuation.", 'details.section:has(> summary:has-text("Arrivals & entry control"))');
await btn("Validate").click({ force: true });
await page.waitForTimeout(2500);
await page.locator(".sheet .alert").first().scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
await shot("Validate", "The server validates the scenario against the network (unknown gates, unreachable destinations, limits) before saving or running.", '.sheet .alert');

// ------------------------------------------------------------------ P-07
journey("P-07", "Run and monitor a simulation", ["R7"], "Run agent-based or macroscopic simulations in the background and follow their progress.");
await goto(`site=${S}&tab=scenarios&view=3d`, 4000);
await page.locator(".list-item", { hasText: "Normal crowd movement" }).first().getByRole("button", { name: "Run" }).click();
await page.waitForTimeout(2500);
await shot("Progress", "Runs execute in worker processes; progress is streamed to the browser (server-sent events). Runs can be cancelled.", '.sheet .list');
await page.waitForTimeout(25000);
await page.reload({ waitUntil: "load" });
await page.waitForSelector(".navrail");
await page.locator(".nav-item", { hasText: "Simulation Runs" }).click();
await page.waitForTimeout(2000);
await shot("Completed runs", "Each run records method, engine version, seed, data snapshot and thresholds; Reproduce re-runs it exactly.", '.sheet .list');

// ------------------------------------------------------------------ P-08
journey("P-08", "Density, queues and bottlenecks", ["R5"], "Replay agents and the density heatmap; inspect zone densities, queues and bottlenecks.");
await goto(`site=${S}&run=${runs.peak_bathing.id}&tab=results&view=3d`, 8000);
await setTime(1000);
await shot("Replay in 3D", "Agent-based peak-arrival run at t = 16 min 40 s: agents, density heatmap and bottleneck markers over the real map.");
await openSection("Bottlenecks");
await shot("Bottlenecks", "Bottlenecks = locations above the configured limit for at least the minimum duration; unresolved ones are flagged.", 'details.section:has(> summary:has-text("Bottlenecks"))');
await page.locator(".seg button", { hasText: "2D" }).click();
await page.waitForTimeout(3000);
await shot("2D density map", "The same frame in the 2D planning map.");

// ------------------------------------------------------------------ P-09
journey("P-09", "Blocked corridor and route failure", ["R7", "R5"], "Block a corridor (or let a route fail mid-run) and re-run with re-routing.");
await goto(`site=${S}&tab=scenarios&view=2d`, 4000);
await page.locator(".list-item", { hasText: "Blocked pedestrian corridor" }).click();
await openSection("Corridors & gates (circulation plan)");
await shot("Disable a corridor", "Corridors can be closed, narrowed or made one-way per scenario; gates can be closed or change role.", 'details.section:has(> summary:has-text("Corridors & gates"))');
await goto(`site=${S}&run=${runs.blocked_corridor.id}&tab=results&view=3d`, 7000);
await setTime(900);
await shot("Re-routed flows", "Macroscopic result with the corridor closed: computed corridor flows show the re-routed pedestrians.", '.kpis');

// ------------------------------------------------------------------ P-10
journey("P-10", "Emergency evacuation", ["R5", "R1"], "Simulate an evacuation with chosen exits, closures and routing strategy; read clearance times.");
await goto(`site=${S}&tab=scenarios&view=3d`, 4000);
await page.locator(".list-item", { hasText: "Emergency evacuation" }).click();
await openSection("Emergency evacuation");
await shot("Configure evacuation", "Trigger time, affected zones, exits and assembly points, routing (nearest / capacity-aware CCRP / assigned), closures and capacity reductions.", 'details.section:has(> summary:has-text("Emergency evacuation"))');
await goto(`site=${S}&run=${runs.evacuation.id}&tab=results&view=3d`, 7000);
await setTime(300);
await shot("Evacuation flows", "Macroscopic evacuation at t = 5 min: corridor flows, bottlenecks and clearance KPIs.", '.kpis');
await openSection("Evacuation");
await shot("Clearance by zone", "Total and per-zone clearance, unreachable evacuees and the CCRP planning estimate. A short clearance time alone does not make a route safe.", 'details.section:has(> summary:has-text("Evacuation"))');

// ------------------------------------------------------------------ P-11
journey("P-11", "Compare baseline and alternative", ["R5"], "Compare two runs with computed metrics and synchronised 3D views.");
await goto(`site=${S}&tab=runs&view=3d`, 4000);
const done = (name) => page.locator(".list-item.col", { hasText: name }).filter({ hasText: "Agent-based" }).filter({ has: page.getByRole("button", { name: "Baseline" }) }).first();
await done("Normal crowd movement").getByRole("button", { name: "Baseline" }).click();
await done("Peak bathing").getByRole("button", { name: "Alternative" }).click();
await page.locator(".nav-item", { hasText: "Compare" }).click();
await page.waitForSelector(".tbl.compare", { timeout: 120000 });
await shot("Metric differences", "Differences are computed from the two runs (clearance, densities, time above limit, waiting, throughput, exit use, bottlenecks).", '.tbl.compare');
await btn("Synchronised 3D side-by-side").click();
await page.waitForTimeout(8000);
await setTime(1000);
await shot("Synchronised 3D", "Two 3D viewers on a shared timeline with synchronised cameras.");

// ------------------------------------------------------------------ P-12
journey("P-12", "Reports, SOP and drill package", ["R5", "R1"], "Download PDF/CSV/GeoJSON outputs and record review and approval.");
await goto(`site=${S}&tab=reports&view=3d`, 4000);
await shot("Reports and exports", "PDF report, CSV, density and bottleneck GeoJSON per run; comparison report; circulation layouts as GeoJSON.", 'details.section:has(> summary:has-text("Simulation reports"))');
const pdfPath = join(OUT, "img", "report.pdf");
writeFileSync(pdfPath, Buffer.from(await (await fetch(`${API}/api/runs/${runs.evacuation.id}/report.pdf`)).arrayBuffer()));
try {
  execFileSync("pdftoppm", ["-r", "70", "-jpeg", "-f", "1", "-l", "3", pdfPath, join(OUT, "img", "report_p")]);
  for (const [i, t, c] of [
    [1, "PDF report – inputs and provenance", "Scenario description, map/data versions, engine and seed, data licences and input assumptions."],
    [3, "PDF report – maps", "Density map and route/bottleneck map computed from the run."],
  ]) {
    const f = `img/report_p-${i}.jpg`;
    cur.steps.push({ title: t, caption: c, img: f, portrait: true });
  }
} catch {
  console.warn("pdftoppm not available - report page images skipped");
}
await goto(`site=${S}&run=${runs.evacuation.id}&tab=results&view=3d`, 5000);
await openSection("Review & approval");
await page.getByLabel("Prepared by", { exact: true }).fill("Planner (R7)");
await page.getByLabel("Reviewed by", { exact: true }).fill("Crowd safety officer (R5)");
await shot("Review and approval record", "Review status, reviewer and approver are stored with the run and printed in the report's approval block.", 'details.section:has(> summary:has-text("Review & approval"))');

// ------------------------------------------------------------------ P-13
journey("P-13", "Observed and forecast counts", ["R7"], "Upload manual or counter counts and compare them with simulated values.");
await goto(`site=${S}&tab=feeds&view=3d`, 4000);
await page.locator(".sheet input[type=file]").setInputFiles(join(ROOT, "data", "examples", "observations_example.csv"));
await btn("Upload").click();
await page.waitForTimeout(2500);
await shot("Upload counts", "Counts are stored as observed or forecast with their source; no live feeds are connected in this release.", 'details.section:has(> summary:has-text("Records"))');
await goto(`site=${S}&run=${runs.normal.id}&tab=results&view=3d`, 6000);
await page.getByLabel("Zone", { exact: true }).selectOption("hold_w");
await page.locator(".chart-title", { hasText: "Count – Holding Area West" }).scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => {});
await shot("Compare with simulation", "Observed/forecast values appear as separate markers on the simulated zone count (example values).", '.chart:has(.chart-title:has-text("Count"))');

// ------------------------------------------------------------------ P-14
journey("P-14", "Density thresholds approval", ["R1", "R5"], "Configure density limits and record approval by the competent authority.");
await goto(`site=${S}&tab=admin&view=3d`, 4000);
await openSection("Density thresholds (configurable)");
await shot("Thresholds and approval status", "Colour breaks and limits per zone type; the default profile is literature-indicative and marked NOT APPROVED.", 'details.section:has(> summary:has-text("Density thresholds"))');

// ------------------------------------------------------------------ cover screens
journey("OVERVIEW", "Application overview", [], "");
await goto(`site=${S}&tab=overview&view=3d`, 6000);
await shot("Overview", "Overview: site KPIs, latest result and quick start.");
await goto(`site=${S}&tab=usecases&view=2d`, 4000);
await shot("Use cases", "Use-case catalogue: each entry opens the screen where it is carried out.");

writeFileSync(join(OUT, "journeys.json"), JSON.stringify({ generated: new Date().toISOString(), journeys }, null, 1));
await browser.close();
console.log(`captured ${n} screenshots`);

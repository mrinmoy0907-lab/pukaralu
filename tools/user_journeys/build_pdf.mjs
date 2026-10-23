// Builds docs/user-journeys.pdf from docs/journeys/journeys.json + screenshots (see capture.mjs).
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(join(dirname(fileURLToPath(import.meta.url)), "../../frontend/package.json"));
const { chromium } = require("playwright");
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const DIR = join(ROOT, "docs", "journeys");
const { generated, journeys } = JSON.parse(readFileSync(join(DIR, "journeys.json"), "utf8"));

const ROLES = {
  R1: ["Mela administrator", "Approves thresholds, SOPs and drill packages; activates zones."],
  R3: ["Zone in-charge", "Reviews zone boundaries and owner departments; confirms and activates zones."],
  R5: ["Crowd safety officer", "Runs and reviews density, bottleneck and evacuation analyses; reviews reports."],
  R7: ["Planner / GIS analyst", "Prepares GIS data, zones, corridors and scenarios; runs simulations."],
};
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const img = (p) => `data:image/jpeg;base64,${readFileSync(join(DIR, p)).toString("base64")}`;
const chips = (roles) => roles.map((r) => `<span class="chip">${r} · ${esc(ROLES[r]?.[0] ?? r)}</span>`).join("");

const uc = journeys.filter((j) => j.id.startsWith("P-"));
const cover = journeys.find((j) => j.id === "OVERVIEW");

function journeyPages(j) {
  const pages = [];
  for (let i = 0; i < j.steps.length; i += 6) pages.push(j.steps.slice(i, i + 6));
  return pages
    .map(
      (steps, pi) => `
  <section class="page">
    <header class="band">
      <div class="logo">PT</div>
      <div class="bt"><b>Pushkaralu Twin</b><span>User journey</span></div>
      <div class="uc">${esc(j.id)}</div>
      <div class="ttl"><h1>${esc(j.title)}${pi ? " (cont.)" : ""}</h1><p>${esc(j.goal)}</p></div>
      <div class="roles">${chips(j.roles)}</div>
    </header>
    <div class="grid n${steps.length}">
      ${steps
        .map(
          (s, k) => `
      <article class="step">
        <div class="sh"><span class="num">${pi * 6 + k + 1}</span><b>${esc(s.title)}</b></div>
        <div class="shot ${s.portrait ? "portrait" : ""} ${s.detail ? "with-detail" : ""}">
          <img class="full" src="${img(s.img)}"/>${s.detail ? `<img class="detail" src="${img(s.detail)}"/>` : ""}
        </div>
        <p>${esc(s.caption)}</p>
      </article>`,
        )
        .join("")}
    </div>
    <footer>SIM DATA – screenshots show synthetic demonstration data and simulated estimates, not surveyed Pushkaralu data. Safety-critical decisions require approval by authorised officials.</footer>
  </section>`,
    )
    .join("");
}

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "Segoe UI", Inter, Roboto, Arial, sans-serif; color: #1c2a3f; }
.page { width: 297mm; height: 210mm; padding: 9mm 10mm 8mm; page-break-after: always; display: flex; flex-direction: column; background: #f3f6fb; position: relative; }
.band { display: grid; grid-template-columns: auto auto auto 1fr auto; align-items: center; gap: 12px; background: #0b1f4b; color: #fff; border-radius: 10px; padding: 9px 14px; }
.logo { width: 34px; height: 34px; border-radius: 8px; background: #f5b400; color: #0b1f4b; display: grid; place-items: center; font-weight: 800; }
.bt { display: flex; flex-direction: column; font-size: 12px; line-height: 1.2; padding-right: 10px; border-right: 1px solid #3b5694; }
.bt span { color: #9fb3dc; font-size: 10px; }
.uc { font-size: 22px; font-weight: 800; letter-spacing: 0.02em; }
.ttl h1 { margin: 0; font-size: 19px; }
.ttl p { margin: 2px 0 0; font-size: 11px; color: #c9d6f0; }
.roles { display: flex; gap: 5px; flex-wrap: wrap; justify-content: flex-end; max-width: 300px; }
.chip { background: #1d5fd6; border-radius: 10px; padding: 2px 8px; font-size: 9.5px; white-space: nowrap; }
.grid { flex: 1; display: grid; gap: 8px; margin-top: 8px; min-height: 0; }
.grid.n1 { grid-template-columns: 1fr; } .grid.n2 { grid-template-columns: 1fr 1fr; }
.grid.n3, .grid.n5, .grid.n6 { grid-template-columns: 1fr 1fr 1fr; } .grid.n4 { grid-template-columns: 1fr 1fr; }
.grid.n4, .grid.n5, .grid.n6 { grid-template-rows: 1fr 1fr; }
.step { background: #fff; border-radius: 10px; box-shadow: 0 1px 4px rgba(16,33,66,.14); padding: 7px 8px; display: flex; flex-direction: column; gap: 5px; min-height: 0; }
.sh { display: flex; align-items: center; gap: 7px; font-size: 12.5px; }
.num { width: 22px; height: 22px; border-radius: 50%; background: #1d5fd6; color: #fff; display: grid; place-items: center; font-weight: 700; font-size: 12px; flex-shrink: 0; }
.shot { flex: 1; min-height: 0; border-radius: 6px; overflow: hidden; border: 1px solid #dde3ec; background: #eef2f7; display: grid; grid-template-columns: 1fr; gap: 4px; padding: 3px; }
.shot.with-detail { grid-template-columns: 1.55fr 1fr; }
.shot img { width: 100%; height: 100%; min-height: 0; object-fit: contain; object-position: center; }
.shot img.detail { background: #fff; border-radius: 4px; box-shadow: 0 0 0 2px #1d5fd6; }
.step p { margin: 0; font-size: 10px; color: #4a5a72; line-height: 1.3; }
footer { font-size: 8.5px; color: #8a1c1c; margin-top: 5px; }
.cover { background: linear-gradient(135deg, #0b1f4b, #12306b 60%, #1d5fd6); color: #fff; padding: 12mm 14mm 9mm; }
.cover h1 { font-size: 30px; margin: 8px 0 2px; }
.cover .sub { color: #c9d6f0; font-size: 14px; margin: 0 0 14px; }
.cover .cols { display: grid; grid-template-columns: 1.05fr 1fr; gap: 14px; flex: 1; min-height: 0; }
.box { background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18); border-radius: 10px; padding: 8px 11px; font-size: 10px; }
.box h3 { margin: 0 0 6px; font-size: 13px; color: #ffd35c; }
.box table { width: 100%; border-collapse: collapse; }
.box td { padding: 2px 4px; border-bottom: 1px solid rgba(255,255,255,.12); vertical-align: top; }
.toc td:first-child { font-weight: 700; width: 46px; }
.cover img { width: 100%; max-height: 72mm; object-fit: contain; border-radius: 8px; border: 1px solid rgba(255,255,255,.25); }
.warn { background: #fde8e8; color: #8a1c1c; border-radius: 8px; padding: 7px 10px; font-size: 10.5px; margin-top: 8px; }
</style></head><body>
<section class="page cover">
  <div style="display:flex;align-items:center;gap:10px"><div class="logo">PT</div><b>Pushkaralu Crowd Digital Twin</b></div>
  <h1>User journeys for all use cases</h1>
  <p class="sub">Step-by-step workflows with screenshots of the running application · generated ${esc(generated.slice(0, 10))}</p>
  <div class="cols">
    <div style="display:flex;flex-direction:column;gap:10px;min-height:0">
      <div class="box toc"><h3>Use cases</h3><table>${uc.map((j) => `<tr><td>${j.id}</td><td>${esc(j.title)}</td><td>${j.roles.join(", ")}</td></tr>`).join("")}</table></div>
      <div class="box"><h3>Roles</h3><table>${Object.entries(ROLES).map(([k, [n, d]]) => `<tr><td><b>${k}</b></td><td><b>${esc(n)}</b> – ${esc(d)}</td></tr>`).join("")}</table>
      <p style="margin:6px 0 0;color:#c9d6f0">Roles are selected in the top bar; the prototype has no login, so approvals are records, not authenticated sign-off.</p></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px">
      ${cover ? cover.steps.map((s) => `<img src="${img(s.img)}"/>`).join("") : ""}
    </div>
  </div>
  <div class="warn">All screenshots use the bundled SIM DATA layouts (synthetic geometry; the Rajahmundry layout is illustrative and placed on the real OpenStreetMap river bank). Simulation results are estimates. Basemap tiles were not reachable in the environment where these screenshots were captured, so the map background appears plain; on a connected computer the selected real basemap is shown.</div>
</section>
${uc.map(journeyPages).join("")}
</body></html>`;

writeFileSync(join(DIR, "user-journeys.html"), html);
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent(html, { waitUntil: "load" });
await page.pdf({ path: join(ROOT, "docs", "user-journeys.pdf"), format: "A4", landscape: true, printBackground: true, preferCSSPageSize: true });
await browser.close();
console.log("wrote docs/user-journeys.pdf");

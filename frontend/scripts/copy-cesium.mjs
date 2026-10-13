// Copies Cesium's static assets (workers, widgets, assets) into public/cesium so
// Vite serves them; CESIUM_BASE_URL points there (see src/main.tsx).
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "cesium", "Build", "Cesium");
const dest = join(root, "public", "cesium");
if (!existsSync(src)) {
  console.warn("cesium build not found; skipping asset copy");
  process.exit(0);
}
mkdirSync(dest, { recursive: true });
for (const d of ["Workers", "ThirdParty", "Assets", "Widgets"]) {
  cpSync(join(src, d), join(dest, d), { recursive: true });
}
console.log("Cesium assets copied to public/cesium");

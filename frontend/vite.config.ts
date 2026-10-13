import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const api = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  define: { CESIUM_BASE_URL: JSON.stringify("/cesium") },
  server: { port: 5173, proxy: { "/api": { target: api, changeOrigin: true } } },
  preview: { port: 4173, proxy: { "/api": { target: api, changeOrigin: true } } },
  build: { chunkSizeWarningLimit: 6000, sourcemap: false },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});

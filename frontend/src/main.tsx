import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "cesium/Build/Cesium/Widgets/widgets.css";
import "ol/ol.css";
import "./styles.css";
import App from "./App";

// Cesium loads workers and assets from here (copied by scripts/copy-cesium.mjs).
(window as unknown as { CESIUM_BASE_URL: string }).CESIUM_BASE_URL = "/cesium";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

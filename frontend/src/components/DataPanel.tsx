import { useEffect, useState } from "react";
import { api, download } from "../api";
import { useStore } from "../store";
import type { Observation } from "../types";
import { Check, Num, Section, Sel, Txt } from "./ui";

export default function DataPanel() {
  const { site, sites, meta, selectSite, toast, fail, set } = useStore();
  const [file, setFile] = useState<File | null>(null);
  const [license, setLicense] = useState("");
  const [attribution, setAttribution] = useState("");
  const [synthetic, setSynthetic] = useState(false);
  const [surveyed, setSurveyed] = useState(false);
  const [pkType, setPkType] = useState("");
  const [typeField, setTypeField] = useState("pk_type");
  const [typeMap, setTypeMap] = useState("");
  const [layer, setLayer] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [obs, setObs] = useState<Observation[]>([]);
  const [obsFile, setObsFile] = useState<File | null>(null);
  const [ns, setNs] = useState({ name: "", lon: 81.78, lat: 17.0, synthetic: false, basemap: "osm" });

  useEffect(() => {
    if (site) api.observations(site.id).then(setObs).catch(() => setObs([]));
  }, [site]);

  if (!site) return null;
  const datasets = site.datasets ?? [];

  async function doImport() {
    if (!file || !site) return;
    const fd = new FormData();
    fd.append("file", file);
    fd.append("license", license);
    fd.append("attribution", attribution);
    fd.append("is_synthetic", String(synthetic));
    fd.append("is_surveyed", String(surveyed));
    if (pkType) fd.append("pk_type", pkType);
    if (typeField) fd.append("type_field", typeField);
    if (typeMap) fd.append("type_map", typeMap);
    if (layer) fd.append("layer", layer);
    setBusy(true);
    try {
      const r = await api.importFile(site.id, fd);
      setResult(r);
      toast("success", r.kind === "dem" ? `Terrain imported (${r.min.toFixed(1)}–${r.max.toFixed(1)} m)` : `Imported ${r.imported} feature(s)`);
      await selectSite(site.id);
      set({ tab: "data" });
    } catch (e) {
      fail(e, "Import");
    } finally {
      setBusy(false);
    }
  }

  async function createSite() {
    try {
      const s = await api.createSite({ name: ns.name, description: "", origin_lon: ns.lon, origin_lat: ns.lat, is_synthetic: ns.synthetic, basemap: ns.basemap });
      set({ sites: await api.sites() });
      await selectSite(s.id);
      toast("success", "Site created. Import or draw its features.");
    } catch (e) {
      fail(e, "Creating site");
    }
  }

  async function uploadObs() {
    if (!obsFile || !site) return;
    const fd = new FormData();
    fd.append("file", obsFile);
    try {
      await api.uploadObservations(site.id, fd);
      setObs(await api.observations(site.id));
      toast("success", "Observations uploaded.");
    } catch (e) {
      fail(e, "Uploading observations");
    }
  }

  return (
    <div>
      <Section title="Site & data provenance">
        <div className="small">
          <b>{site.name}</b> {site.is_synthetic && <span className="badge warn inline">SYNTHETIC</span>}
          <div className="muted">{site.description}</div>
          <div>
            Origin {site.origin[0].toFixed(5)}, {site.origin[1].toFixed(5)} · site version {site.version} · terrain {site.has_terrain ? "imported" : "none (ellipsoid)"}
          </div>
        </div>
        <table className="tbl">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Licence / attribution</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((d) => (
              <tr key={d.id}>
                <td>
                  {d.filename}
                  <div className="muted small">
                    {d.kind} · {d.format} · {d.feature_count} feat. · {d.source_crs}
                  </div>
                </td>
                <td className="small">
                  {d.license}
                  <div className="muted">{d.attribution}</div>
                </td>
                <td className="small">
                  {d.is_synthetic ? "synthetic" : "real"}
                  {d.is_surveyed ? " · surveyed" : " · not surveyed"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="secondary small" onClick={() => download(`/api/sites/${site.id}/export.geojson`)}>
          Export all site features (GeoJSON)
        </button>
      </Section>
      <Section title="Import GIS data">
        <p className="muted small">GeoJSON, GeoPackage, zipped Shapefile, KML (via GDAL/OGR) or a DEM raster (GeoTIFF). Vectors are reprojected to WGS84. A licence must be declared.</p>
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} accept=".geojson,.json,.gpkg,.zip,.kml,.gml,.fgb,.tif,.tiff,.asc,.img" />
        <Txt label="Licence (required)" value={license} onChange={setLicense} />
        <Txt label="Attribution" value={attribution} onChange={setAttribution} />
        <Check label="Synthetic data" checked={synthetic} onChange={setSynthetic} />
        <Check label="Surveyed / verified data" checked={surveyed} onChange={setSurveyed} />
        <Sel
          label="Assign feature type to all features"
          value={pkType}
          options={Object.entries(meta?.feature_types ?? {}).map(([k, v]) => ({ value: k, label: v.label }))}
          onChange={setPkType}
          allowEmpty="— use attribute —"
        />
        {!pkType && (
          <>
            <Txt label="Type attribute" value={typeField} onChange={setTypeField} />
            <Txt label='Value mapping (JSON, e.g. {"footway":"corridor"})' value={typeMap} onChange={setTypeMap} />
          </>
        )}
        <Txt label="Layer (GeoPackage, optional)" value={layer} onChange={setLayer} />
        <button onClick={doImport} disabled={!file || !license.trim() || busy}>
          {busy ? "Importing…" : "Import"}
        </button>
        {result && (
          <div className="alert ok small">
            {result.kind === "dem" ? `Terrain ${result.min.toFixed(1)}–${result.max.toFixed(1)} m` : `Imported ${result.imported} feature(s) from CRS ${result.source_crs}`}
            {result.warnings?.map((w: string, i: number) => (
              <div key={i}>⚠ {w}</div>
            ))}
            {result.rejected?.map((w: string, i: number) => (
              <div key={i} className="warn-text">✗ {w}</div>
            ))}
          </div>
        )}
      </Section>
      <Section title="Observed / forecast counts" open={false}>
        <p className="muted small">
          Manual or uploaded counts (CSV columns: zone_fid, count, kind = observed|forecast, t_offset_s, observed_at, source, notes). They are shown as separate markers next to simulated values and are never mixed with them.
          {!meta?.live_sensor_integration && " Live CCTV/IoT integration is not implemented in this release."}
        </p>
        <input type="file" accept=".csv" onChange={(e) => setObsFile(e.target.files?.[0] ?? null)} />
        <button className="secondary" onClick={uploadObs} disabled={!obsFile}>
          Upload CSV
        </button>
        <div className="small">{obs.length} record(s)</div>
        <table className="tbl">
          <tbody>
            {obs.slice(0, 30).map((o) => (
              <tr key={o.id}>
                <td>{o.zone_fid}</td>
                <td>{o.count}</td>
                <td>{o.kind}</td>
                <td>{o.t_offset_s ?? o.observed_at}</td>
                <td>{o.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Sites" open={false}>
        {sites.map((s) => (
          <div key={s.id} className={`list-item ${s.id === site.id ? "active" : ""}`} onClick={() => selectSite(s.id)}>
            {s.name} {s.is_synthetic && <span className="badge warn inline">synthetic</span>}
          </div>
        ))}
        <div className="muted small">New site (then import surveyed GIS data):</div>
        <Txt label="Name" value={ns.name} onChange={(v) => setNs({ ...ns, name: v })} />
        <div className="grid2">
          <Num label="Origin lon" step={0.0001} value={ns.lon} onChange={(v) => setNs({ ...ns, lon: v ?? 0 })} />
          <Num label="Origin lat" step={0.0001} value={ns.lat} onChange={(v) => setNs({ ...ns, lat: v ?? 0 })} />
        </div>
        <Sel label="Basemap" value={ns.basemap} options={[{ value: "osm", label: "OpenStreetMap tiles" }, { value: "grid", label: "None (grid)" }]} onChange={(v) => setNs({ ...ns, basemap: v })} />
        <Check label="Synthetic site" checked={ns.synthetic} onChange={(v) => setNs({ ...ns, synthetic: v })} />
        <button onClick={createSite} disabled={!ns.name.trim()}>
          Create site
        </button>
      </Section>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { geoJSON, latLngBounds } from "leaflet";

import { num, pct } from "../../lib/format";
import { availabilityColor, nodeStateMeta } from "../../lib/vocabulary";
import { localityKey } from "../../lib/locality";

/**
 * Carte du territoire.
 *
 * National : les 17 régions coloriées par disponibilité (choroplèthe), un
 * clic descend dans la région. Plus bas : la région courante surlignée, et
 * un cercle par province, site ou équipement — placé au barycentre des
 * équipements situés, coloré par disponibilité, dimensionné par les alertes.
 *
 * Les positions viennent des sources (référentiel de l'agence) : un niveau
 * dont aucun équipement n'est situé n'apparaît pas sur la carte, et le
 * nombre d'éléments non placés est annoncé sous la carte.
 */
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';
const BURKINA_BOUNDS = [
  [9.3, -5.7],
  [15.2, 2.5],
];

let regionsCache = null;

function useRegions() {
  const [regions, setRegions] = useState(regionsCache);
  useEffect(() => {
    if (regionsCache) return undefined;
    let active = true;
    fetch("/regions-simplified.geojson")
      .then((response) => {
        const type = response.headers.get("content-type") ?? "";
        return response.ok && !type.includes("text/html") ? response.json() : null;
      })
      .then((data) => {
        regionsCache = data;
        if (active) setRegions(data);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return regions;
}

function Fit({ bounds }) {
  const map = useMap();
  useEffect(() => {
    if (!bounds?.isValid?.()) return;
    // Un seul point (site d'un équipement) : emprise de surface nulle, que
    // fitBounds ne sait pas cadrer — centrage explicite au zoom de quartier.
    if (bounds.getNorthEast().equals(bounds.getSouthWest())) {
      map.setView(bounds.getCenter(), 15);
      return;
    }
    map.fitBounds(bounds, { padding: [16, 16], maxZoom: 16 });
  }, [bounds, map]);
  return null;
}

function TrackSize() {
  const map = useMap();
  useEffect(() => {
    const observer = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map]);
  return null;
}

// Indicateur coloré sur la carte. La disponibilité a son échelle à seuils
// (99 / 97 / 90 %) ; les volumes sont colorés RELATIVEMENT au plus touché du
// niveau affiché, du jaune pâle au rouge, et dessinés en cercles
// proportionnels : on voit où et combien.
const MAP_METRICS = [
  { value: "availability", label: "Disponibilité" },
  { value: "incidents", label: "Incidents iTop", field: "incidents", noun: "incident(s) iTop" },
  { value: "alerts", label: "Alertes", field: "alerts", noun: "alerte(s) active(s)" },
  { value: "down", label: "En panne", field: "down", noun: "équipement(s) en panne" },
];

const VOLUME_SCALE = ["#f6e3a1", "#f2b45c", "#e8833a", "#d9522b", "#b3261e"];

function volumeColor(value, max) {
  if (!value) return "#3f9f6b";
  const ratio = Math.min(1, value / Math.max(1, max));
  return VOLUME_SCALE[Math.min(VOLUME_SCALE.length - 1, Math.floor(ratio * VOLUME_SCALE.length))];
}

export default function TerritoryMap({
  level,
  rows,
  region,
  onSelect,
  height = 380,
  defaultMetric = "availability",
  controls = true,
}) {
  const regions = useRegions();
  const [metric, setMetric] = useState(defaultMetric);
  const metricMeta = MAP_METRICS.find((item) => item.value === metric);
  const metricMax = Math.max(1, ...(rows ?? []).map((row) => row[metricMeta.field] ?? 0));
  const fillFor = (row) =>
    metric === "availability"
      ? availabilityColor(row.availability_pct)
      : volumeColor(row[metricMeta.field] ?? 0, metricMax);

  const byRegion = useMemo(() => {
    const index = new Map();
    if (level === "region") {
      for (const row of rows ?? []) index.set(localityKey(row.name), row);
    }
    return index;
  }, [level, rows]);

  const currentRegion = useMemo(() => {
    if (!regions || !region) return null;
    const feature = regions.features.find(
      (item) => localityKey(item.properties.nom) === localityKey(region),
    );
    return feature ? { ...regions, features: [feature] } : null;
  }, [regions, region]);

  const points = useMemo(
    () =>
      (rows ?? []).filter(
        (row) =>
          level !== "region" &&
          Number.isFinite(Number(row.latitude)) &&
          Number.isFinite(Number(row.longitude)) &&
          row.latitude !== null &&
          row.longitude !== null,
      ),
    [level, rows],
  );
  const unplaced = level === "region" ? 0 : (rows?.length ?? 0) - points.length;

  const bounds = useMemo(() => {
    if (points.length) {
      const b = latLngBounds(points.map((row) => [Number(row.latitude), Number(row.longitude)]));
      // Au niveau du site, on cadre sur ses équipements (zoom de quartier) ;
      // plus haut, la région courante reste entièrement visible.
      if (level === "node") return points.length === 1 ? b : b.pad(0.3);
      if (currentRegion) b.extend(geoJSON(currentRegion).getBounds());
      return points.length === 1 && !currentRegion ? b.pad(0.5) : b;
    }
    if (currentRegion) return geoJSON(currentRegion).getBounds();
    return latLngBounds(BURKINA_BOUNDS);
  }, [points, currentRegion, level]);

  const regionStyle = (feature) => {
    if (level !== "region") {
      return { color: "#0b5f97", weight: 1, opacity: 0.6, fillOpacity: 0 };
    }
    const row = byRegion.get(localityKey(feature.properties.nom));
    return {
      color: "#ffffff",
      weight: 1.2,
      fillColor: row ? fillFor(row) : "#9aa5b1",
      fillOpacity: row ? 0.62 : 0.18,
    };
  };

  return (
    <div className="flex flex-col" style={{ height }}>
      <div className="flex-1 min-h-0">
        <MapContainer
          bounds={BURKINA_BOUNDS}
          maxBounds={[
            [8.5, -6.5],
            [16, 3.3],
          ]}
          scrollWheelZoom
          style={{ height: "100%", width: "100%", background: "var(--surface-inset)" }}
        >
          <TrackSize />
          <Fit bounds={bounds} />
          <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} maxZoom={18} />
          {regions && (
            <GeoJSON
              key={`regions-${level}-${metric}-${rows?.length ?? 0}`}
              data={regions}
              style={regionStyle}
              onEachFeature={(feature, layer) => {
                if (level !== "region") return;
                const row = byRegion.get(localityKey(feature.properties.nom));
                layer.bindTooltip(
                  `<strong>${row?.name ?? feature.properties.nom}</strong><br/>` +
                    (row
                      ? (metricMeta.field ? `<strong>${num(row[metricMeta.field])}</strong> ${metricMeta.noun}<br/>` : "") +
                        `Disponibilité ${pct(row.availability_pct, 1)} · ${num(row.nodes)} équipements<br/>` +
                        `${num(row.down)} en panne · ${num(row.incidents)} incident(s) iTop`
                      : "Aucun équipement suivi"),
                  { sticky: true },
                );
                if (row) layer.on("click", () => onSelect?.(row));
              }}
            />
          )}
          {currentRegion && (
            <GeoJSON
              key={`current-${region}`}
              data={currentRegion}
              style={{ color: "#0b5f97", weight: 2.5, fillColor: "#0b5f97", fillOpacity: 0.06 }}
              interactive={false}
            />
          )}
          {level === "region" &&
            metricMeta.field &&
            (rows ?? [])
              .filter((row) => row[metricMeta.field] > 0 && row.latitude != null && row.longitude != null)
              .map((row) => (
                <CircleMarker
                  key={`vol-${row.key ?? row.name}`}
                  center={[Number(row.latitude), Number(row.longitude)]}
                  radius={5 + 18 * Math.sqrt(row[metricMeta.field] / metricMax)}
                  pathOptions={{ color: "#ffffff", weight: 1.5, fillColor: "#b3261e", fillOpacity: 0.75 }}
                  eventHandlers={{ click: () => onSelect?.(row) }}
                >
                  <Tooltip direction="top" offset={[0, -4]}>
                    <div style={{ fontSize: 12 }}>
                      <strong>{row.name}</strong>
                      <br />
                      {num(row[metricMeta.field])} {metricMeta.noun}
                    </div>
                  </Tooltip>
                </CircleMarker>
              ))}
          {points.map((row) => {
            const color = level === "node" ? nodeStateMeta(row.state).color : fillFor(row);
            const sizeField = metricMeta.field ?? "alerts";
            const share = (row[sizeField] ?? 0) / Math.max(1, ...points.map((item) => item[sizeField] ?? 0));
            return (
              <CircleMarker
                key={row.key}
                center={[Number(row.latitude), Number(row.longitude)]}
                radius={level === "node" ? 7 : 7 + share * 12}
                pathOptions={{ color, weight: 2, fillColor: color, fillOpacity: 0.7 }}
                eventHandlers={{ click: () => onSelect?.(row) }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <div style={{ fontSize: 12, lineHeight: 1.45 }}>
                    <strong>{row.name}</strong>
                    <br />
                    {level === "node" ? (
                      <>
                        {nodeStateMeta(row.state).label} · {num(row.alerts)} alerte(s)
                      </>
                    ) : (
                      <>
                        Disponibilité {pct(row.availability_pct, 1)} · {num(row.nodes)} équip.
                        <br />
                        {num(row.alerts)} alerte(s) · {num(row.incidents)} incident(s)
                      </>
                    )}
                  </div>
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>
      <div
        className="shrink-0 flex items-center gap-3 flex-wrap px-2 py-1 border-t text-[10.5px]"
        style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
      >
        {controls && level !== "node" && (
          <select
            className="select"
            style={{ height: 22, fontSize: 11, width: 130 }}
            value={metric}
            onChange={(event) => setMetric(event.target.value)}
            aria-label="Indicateur affiché sur la carte"
          >
            {MAP_METRICS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        )}
        {metric === "availability" || level === "node"
          ? [99.9, 98, 94, 50].map((value, index) => (
              <span key={value} className="flex items-center gap-1">
                <span className="dot" style={{ background: availabilityColor(value) }} />
                {["≥ 99 %", "97–99 %", "90–97 %", "< 90 %"][index]}
              </span>
            ))
          : (
              <span className="flex items-center gap-1">
                <span className="dot" style={{ background: "#3f9f6b" }} /> aucun
                {VOLUME_SCALE.map((color) => (
                  <span key={color} style={{ background: color, width: 14, height: 8, display: "inline-block" }} />
                ))}
                jusqu'à {num(metricMax)}
              </span>
            )}
        {level !== "node" && (
          <span className="ml-auto">
            {level === "region"
              ? metricMeta.field
                ? `cercle = ${metricMeta.noun}`
                : "clic sur une région pour descendre"
              : `taille = ${metricMeta.field ? metricMeta.noun : "alertes actives"}`}
          </span>
        )}
        {unplaced > 0 && (
          <span style={{ color: "var(--sev-medium)" }}>
            {unplaced} élément{unplaced > 1 ? "s" : ""} sans coordonnées
          </span>
        )}
      </div>
    </div>
  );
}

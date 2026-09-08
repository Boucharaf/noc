import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import "leaflet/dist/leaflet.css";

import { availabilityColor } from "../../lib/vocabulary";
import { num, pct } from "../../lib/format";

/**
 * Carte des sites.
 *
 * Marqueurs en cercles vectoriels et non en épingles : le RAYON porte le
 * volume d'incidents et la COULEUR la disponibilité. Une épingle ne peut
 * coder qu'une seule dimension, or la question posée devant une carte de
 * NOC est toujours double — « où ça va mal » ET « à quel point ».
 *
 * Les sites sans coordonnées sont ÉCARTÉS de la carte mais leur nombre
 * est annoncé sous elle : `dim_locality.latitude` n'est renseignée que
 * par etl/scripts/discover_geography.py, et une carte à moitié vide sans
 * explication se lit comme une panne d'affichage.
 */

// Centre approximatif du Burkina Faso — cadrage par défaut quand aucun
// site n'a encore de coordonnées.
const DEFAULT_CENTER = [12.3, -1.6];
const DEFAULT_ZOOM = 6;

function FitBounds({ points }) {
  const map = useMap();
  useEffect(() => {
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 9);
      return;
    }
    map.fitBounds(points, { padding: [28, 28], maxZoom: 9 });
  }, [map, points]);
  return null;
}

export default function SitesMap({ localities, height = 420, onSelect }) {
  const navigate = useNavigate();

  const located = useMemo(
    () => (localities ?? []).filter((l) => l.latitude != null && l.longitude != null),
    [localities],
  );
  const unlocated = (localities?.length ?? 0) - located.length;

  const maxIncidents = Math.max(1, ...located.map((l) => l.total_incidents ?? 0));
  const points = located.map((l) => [l.latitude, l.longitude]);

  return (
    <div className="flex flex-col" style={{ height }}>
      <div className="flex-1 min-h-0">
        <MapContainer
          center={DEFAULT_CENTER}
          zoom={DEFAULT_ZOOM}
          scrollWheelZoom
          style={{ height: "100%", width: "100%" }}
          attributionControl
        >
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="&copy; OpenStreetMap"
          />
          <FitBounds points={points} />
          {located.map((locality) => {
            const share = (locality.total_incidents ?? 0) / maxIncidents;
            const color = availabilityColor(locality.availability_pct);
            return (
              <CircleMarker
                key={locality.locality_id ?? locality.locality}
                center={[locality.latitude, locality.longitude]}
                radius={6 + share * 14}
                pathOptions={{
                  color,
                  weight: 1.5,
                  fillColor: color,
                  fillOpacity: 0.35,
                }}
                eventHandlers={{
                  click: () =>
                    onSelect
                      ? onSelect(locality)
                      : navigate(`/equipements?locality_id=${locality.locality_id}`),
                }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                    <strong>{locality.locality}</strong>
                    <br />
                    {locality.region}
                    <br />
                    Incidents : {num(locality.total_incidents)} · critiques{" "}
                    {num(locality.critical)}
                    <br />
                    Disponibilité : {pct(locality.availability_pct, 2)}
                    <br />
                    Équipements : {num(locality.nb_nodes)}
                  </div>
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>

      <div
        className="shrink-0 flex items-center gap-3 flex-wrap px-2 py-1.5 border-t text-[10.5px]"
        style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
      >
        <span className="flex items-center gap-1">
          <span className="dot" style={{ background: availabilityColor(99.9) }} /> ≥ 99 %
        </span>
        <span className="flex items-center gap-1">
          <span className="dot" style={{ background: availabilityColor(98) }} /> 97–99 %
        </span>
        <span className="flex items-center gap-1">
          <span className="dot" style={{ background: availabilityColor(94) }} /> 90–97 %
        </span>
        <span className="flex items-center gap-1">
          <span className="dot" style={{ background: availabilityColor(50) }} /> &lt; 90 %
        </span>
        <span className="ml-auto">
          taille du cercle = nombre d'incidents du mois
        </span>
        {unlocated > 0 && (
          <span style={{ color: "var(--sev-medium)" }}>
            {unlocated} site{unlocated > 1 ? "s" : ""} sans coordonnées (non affiché
            {unlocated > 1 ? "s" : ""})
          </span>
        )}
      </div>
    </div>
  );
}

import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { geoJSON } from "leaflet";
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
const BURKINA_BOUNDS = [
  [9.3, -5.7],
  [15.2, 2.5],
];

/**
 * Fond de carte.
 *
 * C'est lui qui fait apparaître les villes, les routes et le relief : la
 * couche GeoJSON ne dessine que la frontière du pays, et les marqueurs
 * que les sites suivis. Sans TileLayer, la carte est un contour vide sur
 * lequel flottent des cercles — exactement ce qui était observé.
 *
 * Fond clair OpenStreetMap : le style routier et les libellés des villes
 * restent visibles comme sur une carte routière classique, quel que soit
 * le thème de l'application.
 */
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function FitBounds({ points, countryGeoJson }) {
  const map = useMap();
  useEffect(() => {
    const countryBounds = countryGeoJson ? geoJSON(countryGeoJson).getBounds() : null;
    if (countryBounds?.isValid()) {
      map.fitBounds(countryBounds, { padding: [18, 18] });
    }
    if (points.length === 0) return;
    if (points.length === 1) {
      map.setView(points[0], 9);
      return;
    }
    map.fitBounds(points, { padding: [28, 28], maxZoom: 9 });
  }, [countryGeoJson, map, points]);
  return null;
}

export default function SitesMap({ localities, height = 420, onSelect }) {
  const navigate = useNavigate();
  const [countryGeoJson, setCountryGeoJson] = useState(null);

  useEffect(() => {
    let active = true;
    fetch("/region.geojson")
      .then((response) => {
        // Si le fichier est absent de /public, nginx et Vite renvoient
        // index.html avec un statut 200 : `response.ok` est alors vrai
        // et `.json()` échoue en silence. On vérifie donc le type.
        const type = response.headers.get("content-type") ?? "";
        if (!response.ok || type.includes("text/html")) {
          console.warn("[SitesMap] /region.geojson introuvable dans public/");
          return null;
        }
        return response.json();
      })
      .then((data) => {
        if (active) setCountryGeoJson(data);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

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
          minZoom={DEFAULT_ZOOM}
          maxBounds={BURKINA_BOUNDS}
          maxBoundsViscosity={1}
          scrollWheelZoom
          style={{ height: "100%", width: "100%", background: "var(--surface-inset)" }}
          attributionControl
        >
          <TileLayer
            url={TILE_URL}
            attribution={TILE_ATTRIBUTION}
            maxZoom={18}
          />
          {countryGeoJson && (
            <GeoJSON
              data={countryGeoJson}
              // Contour seul, sans remplissage : un aplat par-dessus les
              // tuiles masquerait justement les villes qu'on veut voir.
              style={{
                color: "#0b5f97",
                weight: 2,
                opacity: 0.9,
                fillOpacity: 0,
                interactive: false,
              }}
            />
          )}
          <FitBounds points={points} countryGeoJson={countryGeoJson} />
          {located.map((locality) => {
            const share = (locality.total_incidents ?? 0) / maxIncidents;
            const color = availabilityColor(locality.availability_pct);
            return (
              <CircleMarker
                key={locality.locality_id ?? locality.locality}
                center={[locality.latitude, locality.longitude]}
                pane="markerPane"
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

import { useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import { MapPin } from "lucide-react";

import { Modal } from "../ui/Overlay";

/**
 * Localisation cliquable : la localité en clair (site · province ·
 * région) ; un clic ouvre la carte centrée sur le lieu.
 *
 * `position` vient de l'API (`geo_service.position`) : coordonnées de
 * l'équipement, ou, à défaut, barycentre de son site, de sa province ou de
 * sa région. La précision est annoncée — une position approchée ne doit
 * pas passer pour l'emplacement exact de l'équipement.
 */
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

const PRECISION = {
  node: { zoom: 16, label: "position exacte de l'équipement" },
  site: { zoom: 14, label: "position approchée : centre du site" },
  province: { zoom: 10, label: "position approchée : centre de la province" },
  region: { zoom: 9, label: "position approchée : centre de la région" },
};

export default function LocationLink({ site, province, region, position, name, compact = false }) {
  const [open, setOpen] = useState(false);
  const label = [site, province, region].filter(Boolean).join(" · ") || "localité inconnue";
  const located = position?.latitude != null && position?.longitude != null;
  const precision = PRECISION[position?.precision] ?? PRECISION.site;

  if (!located) {
    return (
      <span title="Aucune coordonnée connue pour ce lieu">
        {label}
        {!compact && (
          <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
            non géolocalisé
          </span>
        )}
      </span>
    );
  }

  const center = [Number(position.latitude), Number(position.longitude)];
  return (
    <>
      <button
        type="button"
        className="inline-flex items-start gap-1 text-left"
        style={{ color: "var(--accent-ink)" }}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        title="Voir sur la carte"
      >
        <MapPin size={12} className="shrink-0 mt-[2px]" />
        <span className="underline decoration-dotted underline-offset-2">{label}</span>
      </button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        width={720}
        centered
        title={name ? `${name} — ${label}` : label}
        subtitle={`${precision.label} · ${center[0].toFixed(5)}, ${center[1].toFixed(5)}`}
        footer={
          <a
            className="btn btn-sm"
            href={`https://www.openstreetmap.org/?mlat=${center[0]}&mlon=${center[1]}#map=${precision.zoom}/${center[0]}/${center[1]}`}
            target="_blank"
            rel="noreferrer"
          >
            Ouvrir dans OpenStreetMap
          </a>
        }
      >
        <div style={{ height: 420 }}>
          <MapContainer
            center={center}
            zoom={precision.zoom}
            scrollWheelZoom
            style={{ height: "100%", width: "100%", background: "var(--surface-inset)" }}
          >
            <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} maxZoom={18} />
            <CircleMarker
              center={center}
              radius={position.precision === "node" ? 9 : 14}
              pathOptions={{
                color: "#d64545",
                weight: 2.5,
                fillColor: "#d64545",
                fillOpacity: position.precision === "node" ? 0.75 : 0.25,
                dashArray: position.precision === "node" ? undefined : "4 4",
              }}
            >
              <Tooltip permanent direction="top" offset={[0, -8]}>
                {name ?? position.label ?? label}
              </Tooltip>
            </CircleMarker>
          </MapContainer>
        </div>
      </Modal>
    </>
  );
}

import React, { useEffect, useMemo, useState } from "react";
import {
  MapContainer,
  Marker,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents,
} from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { MousePointerClick } from "lucide-react";
import { useThemeStore } from "../../store/theme";
import { availabilityColor } from "../../theme/colors";

// Bounding box around Burkina Faso (actual extent ~9.4–15.1N, -5.5–2.4E), padded
// so panning stays regionally relevant instead of drifting into open ocean/desert.
const BFA_BOUNDS = [
  [8.6, -6.2],
  [15.9, 3.0],
];
const MIN_R = 6;
const MAX_R = 16;

const markerIcon = ({ color, radius, isSelected, isCritical }) => {
  const size = radius * 2 + 8;
  const pulse = isCritical
    ? `<span class="absolute inset-0 noc-marker-pulse" style="background:${color};"></span>`
    : "";
  return L.divIcon({
    html: `
      <div class="relative flex items-center justify-center" style="width:${size}px;height:${size}px;">
        ${pulse}
        <span class="noc-marker relative${isSelected ? " is-selected" : ""}" style="width:${radius * 2}px;height:${radius * 2}px;background:${color};"></span>
      </div>
    `,
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
};

// Requires a click before scroll-wheel zoom activates — otherwise scrolling the
// dashboard page over the map would get hijacked into zooming it (a common
// embedded-map annoyance). One click "focuses" the map, matching the pattern
// used by most map embeds.
const ScrollZoomGate = ({ onFocus }) => {
  useMapEvents({
    click(e) {
      if (!e.target.scrollWheelZoom.enabled()) {
        e.target.scrollWheelZoom.enable();
        onFocus();
      }
    },
  });
  return null;
};

// The map fills whatever room its card gives it, but never less than this.
//
// It is a min-height rather than a height on purpose: the wrapper is a flex
// item with `flex-1`, i.e. `flex-basis: 0%`, and flex-basis beats the `height`
// property — so a height set here (or passed by a caller) is simply ignored and
// the box is sized from leftover space alone. On a 700px-tall window that left
// the map 124px tall, which renders but is useless. min-height is the one
// dimension the flex algorithm will not shrink past, so it is what actually
// holds the floor; the page scrolls instead, which is the better trade.
const MIN_HEIGHT = 280;

// Leaflet measures its container once, at mount, and only re-measures on a
// window resize. Every resize that matters here is a container one — the card
// reflowing when data arrives, the KPI row wrapping, a panel expanding — and
// none of those fire a window resize, so the map keeps drawing at its old size:
// grey bands where tiles should be, and clicks landing off-target. Watching the
// element itself is the only reliable trigger.
const InvalidateOnResize = () => {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    let frame = 0;
    const observer = new ResizeObserver(() => {
      // rAF-coalesced: a reflow can fire several entries, and invalidateSize
      // does a full redraw.
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => map.invalidateSize());
    });
    observer.observe(container);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [map]);
  return null;
};

const BurkinaFasoMap = ({
  localities = [],
  selectedLocalityId,
  onSelect,
  minHeight = MIN_HEIGHT,
}) => {
  const { theme } = useThemeStore();
  const [focused, setFocused] = useState(false);

  const maxIncidents = Math.max(1, ...localities.map((l) => l.total_incidents));
  const radiusFor = (count) => {
    const t = Math.sqrt(count) / Math.sqrt(maxIncidents);
    return MIN_R + t * (MAX_R - MIN_R);
  };

  const points = useMemo(
    () =>
      localities
        .filter((l) => l.latitude != null && l.longitude != null)
        .map((l) => ({
          ...l,
          r: radiusFor(l.total_incidents),
          color: availabilityColor(l.availability_pct),
        })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [localities, maxIncidents],
  );

  return (
    <div className="flex h-full w-full flex-col">
      {/* `isolate z-0` traps Leaflet's internal z-indexes (panes go up to 1000)
          inside this box, so the map can't paint over the sticky header (z-20)
          when the page scrolls. */}
      <div
        className={`relative isolate z-0 w-full flex-1 overflow-hidden rounded-lg border ${theme === "dark" ? "leaflet-dark-map" : ""}`}
        style={{ minHeight, borderColor: "var(--color-border)" }}
      >
        <MapContainer
          bounds={BFA_BOUNDS}
          maxBounds={BFA_BOUNDS}
          maxBoundsViscosity={0.6}
          minZoom={6}
          maxZoom={12}
          scrollWheelZoom={false}
          attributionControl={false}
          style={{ height: "100%", width: "100%" }}
        >
          <InvalidateOnResize />
          <ScrollZoomGate onFocus={() => setFocused(true)} />
          <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          {points.map((p) => (
            <Marker
              key={p.locality_id}
              position={[p.latitude, p.longitude]}
              icon={markerIcon({
                color: p.color,
                radius: p.r,
                isSelected: p.locality_id === selectedLocalityId,
                isCritical: p.color === "#d03b3b",
              })}
              eventHandlers={{
                click: (e) => {
                  e.target._map.scrollWheelZoom.enable();
                  setFocused(true);
                  onSelect?.(p.locality_id);
                },
              }}
            >
              <Tooltip direction="top" offset={[0, -p.r]} opacity={1}>
                <div className="text-xs">
                  <div className="font-semibold">{p.locality}</div>
                  <div style={{ color: "var(--color-text-secondary)" }}>
                    {p.region}
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <span>
                      <span className="font-semibold">{p.total_incidents}</span>{" "}
                      incident(s)
                    </span>
                    <span style={{ color: p.color }} className="font-semibold">
                      {p.availability_pct}%
                    </span>
                  </div>
                </div>
              </Tooltip>
            </Marker>
          ))}
        </MapContainer>

        {!focused && (
          <div
            className="map-zoom-hint pointer-events-none absolute bottom-3 left-1/2 z-[500] -translate-x-1/2 rounded-full border px-3 py-1.5 text-xs font-medium shadow-sm"
            style={{
              background: "var(--color-surface)",
              borderColor: "var(--color-border-strong)",
              color: "var(--color-text-secondary)",
            }}
          >
            <span className="inline-flex items-center gap-1.5">
              <MousePointerClick className="h-3.5 w-3.5" />
              Cliquez pour activer le zoom molette
            </span>
          </div>
        )}
      </div>

      <div
        className="mt-3 flex shrink-0 flex-wrap items-center gap-4 text-xs"
        style={{ color: "var(--color-text-secondary)" }}
      >
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: availabilityColor(100) }}
          />
          Disponibilité ≥ 97%
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: availabilityColor(93) }}
          />
          90–97%
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ background: availabilityColor(80) }}
          />
          &lt; 90%
        </span>
        <span className="ml-auto">Taille = volume d'incidents</span>
      </div>
    </div>
  );
};

export default BurkinaFasoMap;

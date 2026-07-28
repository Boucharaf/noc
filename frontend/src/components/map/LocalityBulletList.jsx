import React from "react";
import { availabilityColor } from "../../theme/colors";

// Bullet-point list of localities — the accessible/table-view companion to
// BurkinaFasoMap (same data, no hover/SVG required), and a click-to-select
// alternative to the map on small screens or for keyboard navigation.
const LocalityBulletList = ({
  localities = [],
  selectedLocalityId,
  onSelect,
  maxHeight = 'clamp(300px, calc(100vh - 480px), 640px)',
}) => {
  const sorted = [...localities].sort(
    (a, b) => b.total_incidents - a.total_incidents,
  );

  return (
    <ul className="h-full space-y-1 overflow-y-auto pr-1" style={{ maxHeight }}>
      {sorted.map((l) => {
        const isSelected = l.locality_id === selectedLocalityId;
        return (
          <li key={l.locality_id}>
            <button
              type="button"
              onClick={() => onSelect?.(l.locality_id)}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition-colors"
              style={{
                background: isSelected
                  ? "var(--color-accent-soft)"
                  : "transparent",
                color: "var(--color-text-primary)",
              }}
              onMouseEnter={(e) => {
                if (!isSelected)
                  e.currentTarget.style.background = "var(--color-surface-2)";
              }}
              onMouseLeave={(e) => {
                if (!isSelected)
                  e.currentTarget.style.background = "transparent";
              }}
            >
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: availabilityColor(l.availability_pct) }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{l.locality}</span>
                <span
                  className="block truncate text-xs"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {l.region}
                </span>
              </span>
              <span
                className="shrink-0 text-xs font-semibold tabular-nums"
                style={{ color: "var(--color-text-secondary)" }}
              >
                {l.total_incidents}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
};

export default LocalityBulletList;

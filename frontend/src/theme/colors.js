// Validated against the dataviz palette validator (six checks: lightness band,
// chroma floor, CVD separation, contrast) — see scripts/validate_palette.js.
// Do not hand-tweak hues without re-running the validator.

export const CATEGORICAL = {
  light: [
    "#2a78d6",
    "#1baf7a",
    "#eda100",
    "#008300",
    "#4a3aa7",
    "#e34948",
    "#e87ba4",
    "#eb6834",
  ],
  dark: [
    "#3987e5",
    "#199e70",
    "#c98500",
    "#008300",
    "#9085e9",
    "#e66767",
    "#d55181",
    "#d95926",
  ],
};

// Fixed — reserved for state, never reused as a categorical series (same hex both themes).
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  serious: "#ec835a",
  critical: "#d03b3b",
};

export const SEVERITY_COLOR = {
  critical: STATUS.critical,
  high: STATUS.serious,
  medium: STATUS.warning,
  low: STATUS.good,
};

// Chart chrome (grid/axis/ink) per theme — fed into Chart.js options, since CSS
// custom properties aren't visible to the canvas renderer.
export const CHART_CHROME = {
  light: {
    surface: "#ffffff",
    primaryInk: "#0f172a",
    secondaryInk: "#475569",
    mutedInk: "#94a3b8",
    grid: "#e2e8f0",
    axis: "#cbd5e1",
  },
  dark: {
    surface: "#0f1626",
    primaryInk: "#f1f5f9",
    secondaryInk: "#94a3b8",
    mutedInk: "#64748b",
    grid: "rgba(255,255,255,0.08)",
    axis: "rgba(255,255,255,0.16)",
  },
};

export const availabilityColor = (pct) => {
  if (pct == null) return STATUS.good;
  if (pct < 90) return STATUS.critical;
  if (pct < 97) return STATUS.warning;
  return STATUS.good;
};

// What a map marker's colour means, per page. It travels with the palette
// rather than the map component because it is colour policy, not rendering:
// the KPI views colour by monthly availability, while the Carte tab colours by
// the severity of what is open right now. Mixing the two is not cosmetic —
// severity-coloured filter chips above availability-coloured markers made
// ticking "Moyenne" (yellow) light up a map of red dots.
export const AVAILABILITY_SCHEME = {
  colorFor: (l) => availabilityColor(l.availability_pct),
  legend: [
    { color: availabilityColor(99), label: "Disponibilité ≥ 97%" },
    { color: availabilityColor(93), label: "90–97%" },
    { color: availabilityColor(80), label: "< 90%" },
  ],
};

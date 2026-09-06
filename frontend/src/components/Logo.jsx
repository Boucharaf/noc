import React from "react";

/**
 * Inline mark, not a raster import: `assets/images/noc-logo-256.png` was
 * referenced from Header.jsx and Login.jsx but never actually present in the
 * repo, which fails the Vite build the moment either page is touched. An SVG
 * mark styled off the same CSS tokens as the rest of the app also means it
 * never goes stale against a theme change the way a fixed PNG would.
 */
const Logo = ({ size = 36, className = "" }) => (
  <svg
    viewBox="0 0 40 40"
    width={size}
    height={size}
    className={className}
    role="img"
    aria-label="RESINA NOC"
  >
    <rect x="0.5" y="0.5" width="39" height="39" rx="4" fill="var(--color-surface-2)" stroke="var(--color-border-strong)" />
    {/* three signal bars of rising height — a supervision readout, not a generic shield/globe glyph */}
    <rect x="9" y="21" width="5" height="10" rx="1" fill="var(--color-text-muted)" />
    <rect x="17.5" y="15" width="5" height="16" rx="1" fill="var(--color-accent)" />
    <rect x="26" y="9" width="5" height="22" rx="1" fill="var(--color-signal)" />
  </svg>
);

export default Logo;

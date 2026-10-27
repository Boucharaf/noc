import { useMemo } from "react";

import { useUiStore } from "../../store/ui";

/**
 * Habillage commun des graphiques.
 *
 * Chart.js dessine sur un canvas : il ne voit PAS les variables CSS du
 * thème. Les couleurs de grille, d'axe et d'encre doivent donc lui être
 * passées en dur, recalculées à chaque changement de thème — d'où ce
 * hook plutôt qu'un objet constant.
 *
 * Parti pris de lisibilité, valable pour tous les graphes de cette
 * application : grille horizontale seulement, pas de bordure d'axe, pas
 * de légende quand il n'y a qu'une série, points masqués sauf au survol.
 * Une courbe de latence sur 24 h compte 288 points ; les dessiner tous
 * en cercles pleins produit une chenille, pas une tendance.
 */
export function useChartTheme() {
  const theme = useUiStore((s) => s.theme);

  return useMemo(() => {
    const dark = theme !== "light";
    return {
      dark,
      ink: dark ? "#e6edf6" : "#0f1a2b",
      inkMuted: dark ? "#5d6b80" : "#8494a8",
      grid: dark ? "rgba(255,255,255,.06)" : "rgba(15,23,42,.08)",
      surface: dark ? "#161f2e" : "#ffffff",
      border: dark ? "rgba(255,255,255,.14)" : "rgba(15,23,42,.16)",
    };
  }, [theme]);
}

/**
 * Couleur utilisable sur un canvas.
 *
 * Les couleurs du vocabulaire sont des variables CSS (`var(--sev-info)`) :
 * passées telles quelles à Chart.js, elles sont refusées par le canvas, qui
 * retombe sur le NOIR — courbes et aires noires sur fond sombre. On les
 * résout ici en valeur réelle, avec une opacité facultative.
 */
export function canvasColor(color, alpha = 1) {
  if (!color) return color;
  let value = color;
  const match = /^var\((--[^),\s]+)\)$/.exec(String(color).trim());
  if (match && typeof document !== "undefined") {
    value = getComputedStyle(document.documentElement).getPropertyValue(match[1]).trim() || "#7a8699";
  }
  if (alpha >= 1) return value;
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const digits = hex[1].length === 3 ? hex[1].replace(/./g, "$&$&") : hex[1];
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16));
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(value);
  if (rgb) {
    const [r, g, b] = rgb[1].split(",").map((part) => part.trim());
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return value;
}

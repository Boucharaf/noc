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

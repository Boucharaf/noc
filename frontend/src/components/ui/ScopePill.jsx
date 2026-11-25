import { fullScopeLabel, scopeLabel, useScopeStore } from "../../store/scope";
import { windowLabel, useWindowStore } from "../../store/ui";

/**
 * Pastille « périmètre · période » d'un bloc (INC-28, INC-32, INC-34).
 *
 * Chaque bloc dit ce qui s'applique à LUI : l'exploitant ne devine plus si
 * la courbe suit le filtre ou la période choisis.
 *
 *   period="window"  → la période globale (« 30 j ») ;
 *   period="live"    → « instantané » : l'état à cet instant ;
 *   period="24 h"    → une fenêtre fixe, écrite telle quelle (historique
 *                      court, par exemple) ;
 *   territorial      → le bloc ne sait filtrer que par localité (agrégats
 *                      journaliers, journal historique) : si organisation ou
 *                      type sont choisis, la pastille le signale.
 */
export default function ScopePill({ period = "live", territorial = false }) {
  const scope = useScopeStore();
  const hours = useWindowStore((s) => s.hours);
  const attributes = Boolean(scope.organisation || scope.nodeType);
  const place = territorial ? scopeLabel(scope) : fullScopeLabel(scope);
  const when =
    period === "window" ? windowLabel(hours) : period === "live" ? "instantané" : period;
  const ignored = territorial && attributes;

  return (
    <span
      className="inline-flex items-center gap-1 text-[12px] px-1.5 py-px rounded-[3px] whitespace-nowrap"
      style={{
        color: ignored ? "var(--sev-medium)" : "var(--ink-3)",
        background: "color-mix(in srgb, var(--ink-3) 10%, transparent)",
      }}
      title={
        ignored
          ? "Ce bloc est calculé par localité : les filtres Organisation et Type ne s'y appliquent pas."
          : "Périmètre et période appliqués à ce bloc"
      }
    >
      {place} · {when}
      {ignored && " · org./type non appliqués"}
    </span>
  );
}

import { AlertTriangle } from "lucide-react";

import { failingFor, toolNames } from "../../lib/sources";
import { useSourceHealth } from "../../hooks/queries";

/**
 * « iTop en erreur — données incomplètes » sous une tuile ou en tête d'un
 * bloc dont la source ne répond pas (INC-24, AM-23). Rien si tout va bien,
 * ou si l'utilisateur n'a pas accès à l'état de la collecte.
 *
 * `sources` : une clé de SOURCE_DEPENDENCIES (« incidents », « metrics »…)
 * ou une liste d'outils.
 */
export default function SourceWarning({ sources, inline = false }) {
  const health = useSourceHealth();
  const failing = failingFor(health.data?.tools, sources);
  if (!failing.length) return null;
  const stamp = failing
    .map((tool) => tool.last_success_at)
    .filter(Boolean)
    .sort()[0];
  const since = stamp
    ? new Date(stamp).toLocaleString("fr-FR", {
        timeZone: "Africa/Ouagadougou",
        // Une donnée d'un autre jour sans sa date passerait pour celle du jour.
        ...(Date.now() - Date.parse(stamp) > 86_400_000
          ? { day: "2-digit", month: "2-digit", year: "numeric" }
          : {}),
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  const text = `${toolNames(failing)} ${failing.every((tool) => tool.data_until) ? "à l'arrêt" : "en erreur"} — ${
    since ? `dernière donnée ${since}` : "aucune donnée reçue"
  }`;
  return (
    <span
      className={`${inline ? "inline-flex" : "flex"} items-center gap-1 text-[12px] leading-tight`}
      style={{ color: "var(--sev-medium)" }}
      title={`${text}. Les chiffres qui dépendent de cette source sont incomplets ou figés à la dernière collecte réussie.`}
      role="status"
    >
      <AlertTriangle size={11} aria-hidden="true" className="shrink-0" />
      <span className="min-w-0">{text}</span>
    </span>
  );
}

import { Link } from "react-router-dom";

import { ageFrom, ellipsis } from "../../lib/format";
import { severityMeta } from "../../lib/vocabulary";
import { useOpenAlerts } from "../../hooks/queries";

/**
 * Bandeau défilant des alertes non traitées.
 *
 * Ne s'affiche QUE s'il y a des critiques ou des majeurs non acquittés.
 * Un ticker permanent qui fait défiler « RAS » devient invisible en
 * quelques heures : le simple fait qu'il apparaisse est déjà une
 * information. C'est aussi pour cette raison qu'on n'y met pas les
 * incidents déjà acquittés — quelqu'un s'en occupe, ils n'ont plus à
 * réclamer l'attention de toute la salle.
 *
 * Le contenu est dupliqué une fois : l'animation translate de −50 %, ce
 * qui donne une boucle sans à-coup quel que soit le nombre d'éléments.
 */
export default function AlertTicker() {
  const { data } = useOpenAlerts({ limit: 30 });

  const urgent = (data ?? []).filter(
    (alert) =>
      alert.status === "open" && (alert.severity === "critical" || alert.severity === "high"),
  );

  if (urgent.length === 0) return null;

  // Vitesse proportionnelle au contenu : ~4,5 s par élément, plancher à
  // 20 s pour qu'un ticker à deux entrées ne clignote pas.
  const durationSeconds = Math.max(20, urgent.length * 4.5);

  const items = urgent.map((alert) => {
    const meta = severityMeta(alert.severity);
    return (
      <Link
        key={alert.id}
        to={`/incidents?id=${alert.id}`}
        className="inline-flex items-center gap-1.5 px-3 shrink-0"
        style={{ textDecoration: "none", color: "var(--ink-2)" }}
      >
        <span className="dot" style={{ background: meta.color }} />
        <span className="font-semibold text-[11px]" style={{ color: meta.color }}>
          {meta.short}
        </span>
        <span className="text-[11.5px] font-medium" style={{ color: "var(--ink)" }}>
          {alert.node_name}
        </span>
        <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
          {alert.locality}
        </span>
        <span className="text-[11.5px]">{ellipsis(alert.description, 70)}</span>
        <span className="num text-[11px]" style={{ color: "var(--sev-medium)" }}>
          {ageFrom(alert.detected_at)}
        </span>
      </Link>
    );
  });

  return (
    <div
      className="overflow-hidden border-b shrink-0 flex items-center"
      style={{
        height: "var(--ticker-h)",
        borderColor: "var(--border)",
        background: "color-mix(in srgb, var(--sev-critical) 7%, var(--surface))",
      }}
      role="marquee"
      aria-label="Alertes non acquittées"
    >
      <span
        className="shrink-0 px-2.5 h-full flex items-center gap-1.5 border-r text-[10px] font-bold uppercase tracking-[0.08em]"
        style={{ borderColor: "var(--border)", color: "var(--sev-critical)" }}
      >
        <span className="live-dot" style={{ background: "var(--sev-critical)" }} />
        {urgent.length} non acquittée{urgent.length > 1 ? "s" : ""}
      </span>
      <div className="overflow-hidden flex-1">
        <div className="ticker-track" style={{ animationDuration: `${durationSeconds}s` }}>
          <div className="flex">{items}</div>
          <div className="flex" aria-hidden="true">
            {items}
          </div>
        </div>
      </div>
    </div>
  );
}

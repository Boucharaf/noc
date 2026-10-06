import { Link } from "react-router-dom";

/**
 * Panneau — brique de base de toutes les pages.
 *
 * Un panneau porte TOUJOURS un titre, et le plus souvent un « lien de
 * descente » (`to`) vers l'écran détaillé correspondant. C'est ce qui
 * matérialise le drill-down demandé par le document métier
 * (KPI global → ministère → site → équipement → incident) : chaque bloc
 * de synthèse doit dire où aller pour en savoir plus, sinon la synthèse
 * devient un cul-de-sac.
 */
export default function Panel({
  title,
  subtitle,
  actions,
  to,
  toLabel = "Détail",
  accent,
  flush = false,
  scroll = false,
  className = "",
  bodyClassName = "",
  children,
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        {accent && (
          <span
            className="dot"
            style={{ background: accent }}
            aria-hidden="true"
          />
        )}
        <h2 className="panel-title">{title}</h2>
        {subtitle && (
          <span className="text-[11px] truncate" style={{ color: "var(--ink-3)" }}>
            {subtitle}
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">
          {actions}
          {to && (
            <Link to={to} className="btn btn-ghost btn-sm">
              {toLabel} ›
            </Link>
          )}
        </div>
      </header>
      <div
        className={`${flush ? "panel-body-flush" : "panel-body"} ${
          scroll ? "scroll-y" : ""
        } ${bodyClassName}`}
      >
        {children}
      </div>
    </section>
  );
}

/** Grille de panneaux — 12 colonnes, gouttière serrée (densité NOC). */
export function PanelGrid({ children, className = "" }) {
  return (
    <div className={`grid grid-cols-12 gap-2 ${className}`}>{children}</div>
  );
}

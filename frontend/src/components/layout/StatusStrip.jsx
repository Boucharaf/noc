import { Link } from "react-router-dom";

import { ageFrom, num } from "../../lib/format";
import { useAlertSummary, useNodeStates } from "../../hooks/queries";

/**
 * Bandeau d'état permanent.
 *
 * C'est le cœur du parti pris « vrai NOC » : où qu'il soit dans
 * l'application, un exploitant doit voir sans cliquer combien d'alertes
 * critiques sont ouvertes, combien ne sont pas acquittées, depuis
 * combien de temps la plus ancienne attend, et combien d'équipements
 * sont tombés. Un dashboard qui cache ces quatre chiffres derrière un
 * onglet oblige à revenir « à l'accueil » pour savoir si la situation
 * s'est aggravée pendant qu'on traitait un ticket.
 *
 * L'ancienneté du plus ancien non acquitté est délibérément mise au même
 * niveau que les compteurs : un total stable de 12 alertes peut cacher
 * une critique oubliée depuis six heures, et c'est elle qui coûte le SLA.
 */

function Counter({ label, value, color, to, title, alert = false }) {
  const content = (
    <span className="flex items-baseline gap-1" title={title}>
      <span
        className={`num font-semibold ${alert ? "blink-critical" : ""}`}
        style={{ fontSize: 14, color }}
      >
        {num(value, "0")}
      </span>
      <span className="text-[10px] uppercase tracking-[0.06em]" style={{ color: "var(--ink-3)" }}>
        {label}
      </span>
    </span>
  );

  return to ? (
    <Link to={to} style={{ textDecoration: "none" }} className="hover:opacity-80">
      {content}
    </Link>
  ) : (
    content
  );
}

export default function StatusStrip({ canSeeIncidents }) {
  const summary = useAlertSummary();
  const states = useNodeStates();

  const s = summary.data;
  const n = states.data;
  const incidentsHref = canSeeIncidents ? "/incidents" : null;

  return (
    <div className="flex items-center gap-3.5 flex-wrap">
      <Counter
        label="Critiques"
        value={s?.critical}
        color={s?.critical ? "var(--sev-critical)" : "var(--ink-2)"}
        alert={Boolean(s?.critical)}
        to={incidentsHref ? `${incidentsHref}?severity=critical&status=open` : null}
        title="Incidents critiques ouverts ou acquittés, hors maintenance planifiée"
      />
      <Counter
        label="Majeurs"
        value={s?.high}
        color={s?.high ? "var(--sev-high)" : "var(--ink-2)"}
        to={incidentsHref ? `${incidentsHref}?severity=high` : null}
        title="Incidents de gravité majeure encore ouverts"
      />
      <Counter
        label="Non acquittés"
        value={s?.unacknowledged}
        color={s?.unacknowledged ? "var(--sev-medium)" : "var(--ink-2)"}
        to={incidentsHref ? `${incidentsHref}?status=open` : null}
        title="Personne n'a encore pris ces incidents en compte"
      />
      <Counter
        label="Équip. HS"
        value={n?.down}
        color={n?.down ? "var(--state-down)" : "var(--ink-2)"}
        to="/equipements?state=down"
        title="Équipements hors service : incident bloquant ouvert ou disponibilité nulle"
      />

      {s?.oldest_unacknowledged_at && (
        <span
          className="text-[10.5px] flex items-center gap-1 pl-3.5 border-l"
          style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
          title="Ancienneté de l'alerte non acquittée la plus ancienne — l'indicateur de tension réel du NOC"
        >
          plus ancienne non acquittée
          <span className="num" style={{ color: "var(--sev-medium)" }}>
            {ageFrom(s.oldest_unacknowledged_at)}
          </span>
        </span>
      )}

      {s && (s.opened_last_hour > 0 || s.resolved_last_hour > 0) && (
        <span
          className="text-[10.5px] flex items-center gap-1.5 pl-3.5 border-l"
          style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
          title="Mouvement sur la dernière heure : ouvertures vs résolutions"
        >
          1 h
          <span className="num" style={{ color: "var(--sev-high)" }}>
            +{s.opened_last_hour}
          </span>
          <span className="num" style={{ color: "var(--state-up)" }}>
            −{s.resolved_last_hour}
          </span>
        </span>
      )}
    </div>
  );
}

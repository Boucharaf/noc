import { Link } from "react-router-dom";

import { Meter } from "../ui/Stat";
import { complianceColor, resolutionCodeLabel } from "../../lib/itop";
import { duration, num, pct } from "../../lib/format";
import { availabilityColor } from "../../lib/vocabulary";

/**
 * Blocs « incidents » du document métier, lus sur les tickets iTop :
 * grille des KPI avec cible et statut, équipements récurrents, sites les plus
 * incidentés, causes et organisations.
 */

/**
 * Cibles de la grille « KPI Incidents NOC » du document de l'agence
 * (Résumé éléments pertinents pour le métier). `max` : le réel doit rester
 * en dessous ; `min` : au-dessus.
 */
const SCORECARD = [
  { key: "total", label: "Incidents ouverts sur 30 j", max: 100, format: num },
  { key: "open", label: "Incidents en cours", max: 20, format: num },
  { key: "critical", label: "Incidents critiques (30 j)", max: 5, format: num },
  { key: "high", label: "Incidents majeurs (30 j)", max: 10, format: num },
  { key: "resolution_rate", label: "Taux de résolution", min: 95, format: (v) => pct(v, 1), unit: "%" },
  { key: "overdue", label: "Incidents en retard", max: 5, format: num },
  { key: "recurrent", label: "Incidents récurrents", max: 10, format: num },
  { key: "mtta", label: "MTTA — prise en charge", max: 15, format: duration },
  { key: "mttr", label: "MTTR — résolution", max: 240, format: duration },
  { key: "sla", label: "Respect des SLA", min: 95, format: (v) => pct(v, 1), unit: "%" },
  { key: "without_cause", label: "Incidents sans cause identifiée", max: 5, format: (v) => pct(v, 1), unit: "%" },
  { key: "reopened", label: "Incidents réouverts", max: 5, format: (v) => pct(v, 1), unit: "%" },
  { key: "unassigned", label: "Incidents non affectés", max: 5, format: num },
  { key: "critical_unassigned", label: "Critiques non traités", max: 0, format: num },
];

const VERDICT = {
  ok: { label: "Conforme", color: "var(--state-up)" },
  watch: { label: "À surveiller", color: "var(--sev-medium)" },
  ko: { label: "Non conforme", color: "var(--sev-critical)" },
};

/** Écart toléré avant « non conforme » : 10 % de la cible, au moins une unité. */
function verdict(row, value) {
  if (value == null) return null;
  const target = row.max ?? row.min;
  const gap = row.max != null ? value - row.max : row.min - value;
  if (gap <= 0) return VERDICT.ok;
  if (target > 0 && gap <= Math.max(1, target * 0.1)) return VERDICT.watch;
  return VERDICT.ko;
}

function targetLabel(row) {
  const value = row.max ?? row.min;
  const shown = row.format === duration ? duration(value) : `${num(value)}${row.unit ? ` ${row.unit}` : ""}`;
  if (row.max === 0) return "0";
  return `${row.max != null ? "≤" : "≥"} ${shown}`;
}

/**
 * Valeurs réelles de la grille, assemblées depuis trois sources : l'historique
 * iTop de la période (`kpis`), la file iTop en cours (`open`) et le SLA de la
 * période (`sla`).
 */
function scorecardValues({ kpis, open, sla }) {
  return {
    total: kpis?.total,
    open: open?.total,
    critical: kpis?.by_severity?.critical,
    high: kpis?.by_severity?.high,
    resolution_rate: kpis?.resolution_rate_pct,
    overdue: open?.sla_breached,
    recurrent: kpis?.recurrent_incidents,
    mtta: sla?.mtto_minutes,
    mttr: sla?.mttr_minutes,
    sla: sla?.compliance_pct,
    without_cause: kpis?.without_cause_pct,
    reopened: kpis?.reopened_pct,
    unassigned: open?.unassigned,
    critical_unassigned: open?.critical_unassigned,
  };
}

export function IncidentScorecard({ kpis, open, sla }) {
  const values = scorecardValues({ kpis, open, sla });
  const rows = SCORECARD.filter((row) => values[row.key] != null);
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Indicateur</th>
          <th style={{ textAlign: "right", width: 84 }}>Cible</th>
          <th style={{ textAlign: "right", width: 84 }}>Réel</th>
          <th style={{ width: 104 }}>Statut</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const value = values[row.key];
          const status = verdict(row, value);
          return (
            <tr key={row.key}>
              <td>{row.label}</td>
              <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                {targetLabel(row)}
              </td>
              <td className="num font-medium" style={{ textAlign: "right", color: status?.color }}>
                {row.format(value)}
              </td>
              <td>
                {status && (
                  <span className="text-[11.5px] font-medium" style={{ color: status.color }}>
                    {status.label}
                  </span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function RecurrentTable({ rows }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Équipement</th>
          <th style={{ textAlign: "right", width: 70 }}>Tickets</th>
          <th style={{ textAlign: "right", width: 70 }}>Critiques</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.node_key ?? row.name}>
            <td>
              {row.node_key ? (
                <Link
                  to={`/equipements/${encodeURIComponent(row.node_key)}`}
                  className="font-medium hover:underline"
                  style={{ color: "var(--ink)", textDecoration: "none" }}
                >
                  {row.name}
                </Link>
              ) : (
                <span className="font-medium">{row.name}</span>
              )}
              <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                {row.site || "site non renseigné"}
              </span>
            </td>
            <td className="num" style={{ textAlign: "right" }}>{num(row.incidents)}</td>
            <td
              className="num"
              style={{ textAlign: "right", color: row.critical ? "var(--sev-critical)" : "var(--ink-3)" }}
            >
              {num(row.critical, "0")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function TopSitesTable({ rows }) {
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Site</th>
          <th style={{ textAlign: "right", width: 64 }}>Tickets</th>
          <th style={{ textAlign: "right", width: 64 }}>Critiques</th>
          <th style={{ textAlign: "right", width: 72 }}>Hors délai</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.site}>
            <td>
              <Link
                to={`/equipements?site=${encodeURIComponent(row.site)}`}
                className="font-medium hover:underline"
                style={{ color: "var(--ink)", textDecoration: "none" }}
              >
                {row.site}
              </Link>
              {row.region && (
                <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                  {row.region}
                </span>
              )}
            </td>
            <td className="num" style={{ textAlign: "right" }}>{num(row.incidents)}</td>
            <td
              className="num"
              style={{ textAlign: "right", color: row.critical ? "var(--sev-critical)" : "var(--ink-3)" }}
            >
              {num(row.critical, "0")}
            </td>
            <td
              className="num"
              style={{ textAlign: "right", color: row.breached ? "var(--sev-critical)" : "var(--ink-3)" }}
            >
              {num(row.breached, "0")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function CauseList({ causes }) {
  return (
    <div className="space-y-1">
      {causes.map((cause) => (
        <div key={cause.cause}>
          <div className="flex items-baseline gap-2 text-[12px]">
            <span className="flex-1 truncate">{resolutionCodeLabel(cause.cause)}</span>
            <span className="num" style={{ color: "var(--ink-3)" }}>{num(cause.count)}</span>
            <span className="num" style={{ width: 44, textAlign: "right" }}>
              {pct(cause.share_pct, 0)}
            </span>
          </div>
          <Meter value={cause.share_pct} height={3} />
        </div>
      ))}
    </div>
  );
}

/**
 * Disponibilité par organisation (instantané) croisée avec les incidents
 * iTop de la période : la « disponibilité par ministère/structure ».
 */
export function OrganisationTable({ organisations, incidents }) {
  const byName = new Map((incidents ?? []).map((row) => [row.organisation, row]));
  const showIncidents = byName.size > 0;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Organisation</th>
          <th style={{ width: 150 }}>Disponibilité</th>
          <th style={{ textAlign: "right", width: 56 }}>Panne</th>
          {showIncidents && <th style={{ textAlign: "right", width: 68 }}>Incidents</th>}
          {showIncidents && <th style={{ textAlign: "right", width: 56 }}>SLA</th>}
        </tr>
      </thead>
      <tbody>
        {organisations.map((row) => {
          const itop = byName.get(row.organisation);
          return (
            <tr key={row.organisation}>
              <td>
                <span className="font-medium">{row.organisation}</span>
                <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                  {num(row.nodes)} équipements
                </span>
              </td>
              <td>
                <div className="flex items-center gap-2">
                  <div className="flex-1">
                    <Meter value={row.availability_pct} color={availabilityColor(row.availability_pct)} />
                  </div>
                  <span
                    className="num text-[11.5px]"
                    style={{ minWidth: 44, color: availabilityColor(row.availability_pct) }}
                  >
                    {pct(row.availability_pct, 1)}
                  </span>
                </div>
              </td>
              <td className="num" style={{ textAlign: "right", color: row.down ? "var(--state-down)" : undefined }}>
                {num(row.down)}
              </td>
              {showIncidents && (
                <td className="num" style={{ textAlign: "right" }}>{num(itop?.incidents, "0")}</td>
              )}
              {showIncidents && (
                <td className="num" style={{ textAlign: "right", color: complianceColor(itop?.compliance_pct) }}>
                  {pct(itop?.compliance_pct, 0)}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

import { Link } from "react-router-dom";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { SeverityBadge } from "../components/ui/Badge";
import { availabilityPct, date, dateTime, decimal, duration, monthLabel, num, pct } from "../lib/format";
import { toolLabel } from "../lib/vocabulary";
import { scopeLabel, useScopeStore } from "../store/scope";
import { usePeriodStore } from "../store/ui";
import { useHistoryMonth } from "../hooks/queries";

/**
 * Tableau de bord d'un MOIS PASSÉ.
 *
 * Remplace les écrans en direct dès qu'un autre mois que le mois en cours est
 * choisi dans la barre : leurs tuiles décrivent l'instant présent et n'ont pas
 * de sens pour août. Tout vient du journal du NOC et des journaux de pannes
 * des outils, bornés au mois.
 */
export default function MonthView() {
  const month = usePeriodStore((s) => s.month);
  const year = usePeriodStore((s) => s.year);
  const scope = useScopeStore();
  const query = useHistoryMonth({ year, month });

  return (
    <div className="space-y-3.5">
      <PageHeader
        title={`Tableau de bord — ${monthLabel(month, year)}`}
        subtitle={`${scopeLabel(scope)} · données de ce mois uniquement`}
      />
      <QueryBoundary
        query={query}
        skeleton={<SkeletonRows rows={10} columns={5} />}
        empty={(d) =>
          d?.available === false ||
          (!d?.availability?.subjects && !d?.alerts?.rows?.length && !d?.days?.length)
        }
        emptyMessage="Aucune donnée pour ce mois"
        emptyHint="Aucun outil n'a de donnée sur cette période."
      >
        {(d) => <Month data={d} />}
      </QueryBoundary>
    </div>
  );
}

function Month({ data }) {
  const { availability, alerts, days } = data;
  const points = days.filter((day) => day.availability_pct != null);
  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          label="Disponibilité du mois"
          value={pct(availability.average_pct, 2)}
          hint={`${num(availability.subjects)} équipement(s) supervisé(s)`}
        />
        <Stat label="Pannes" value={num(availability.failures)} />
        <Stat label="MTTR" value={duration(availability.mttr_minutes)} />
        <Stat
          label={alerts.closed == null ? "Apparues, non corrigées" : "Alertes apparues"}
          value={num(alerts.opened)}
          hint={`dont ${num(alerts.opened_by_severity?.critical ?? 0)} critique(s)`}
        />
        <Stat
          label="Alertes corrigées"
          value={alerts.closed == null ? "Non suivi" : num(alerts.closed)}
          hint={alerts.journal_since ? `journal tenu depuis le ${date(alerts.journal_since)}` : undefined}
        />
        <Stat label="Antérieures non corrigées" value={num(alerts.earlier_open)} />
      </div>

      {points.length > 1 && (
        <Panel title="Évolution quotidienne" subtitle="disponibilité moyenne du parc supervisé">
          <LineChart
            height={180}
            labels={points.map((day) => `${day.day.slice(8)}/${day.day.slice(5, 7)}`)}
            valueFormatter={(value) => `${decimal(value, 1)} %`}
            series={[
              {
                label: "Disponibilité",
                data: points.map((day) => day.availability_pct),
                color: "var(--accent)",
                fill: true,
              },
            ]}
          />
        </Panel>
      )}

      <Panel title="Les moins disponibles" flush>
        <div className="overflow-x-auto">
          <table className="tbl">
            <thead>
              <tr>
                <th>Équipement</th>
                <th>Site</th>
                <th style={{ textAlign: "right" }}>Disponibilité</th>
                <th style={{ textAlign: "right" }}>Hors service</th>
                <th style={{ textAlign: "right" }}>Pannes</th>
              </tr>
            </thead>
            <tbody>
              {availability.rows.map((row) => (
                <tr key={row.subject_id}>
                  <td>
                    <Link to={`/equipements/${encodeURIComponent(row.node_id)}`} className="hover:underline">
                      {row.name}
                    </Link>
                  </td>
                  <td>{row.site ?? "—"}</td>
                  <td className="num" style={{ textAlign: "right" }}>{availabilityPct(row.availability_pct, 2)}</td>
                  <td className="num" style={{ textAlign: "right" }}>{duration(row.minutes?.down ?? 0)}</td>
                  <td className="num" style={{ textAlign: "right" }}>{num(row.down_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Alertes du mois"
        subtitle={`${num(alerts.opened)} apparue(s) dans le mois${
          alerts.closed == null ? " et jamais corrigée(s)" : ""
        }, ${num(
          alerts.earlier_open,
        )} antérieure(s) encore non corrigée(s)${
          alerts.opened + alerts.earlier_open > alerts.rows.length
            ? ` · ${num(alerts.rows.length)} plus récentes affichées`
            : ""
        }`}
        flush
      >
        <div className="overflow-x-auto" style={{ maxHeight: 520, overflowY: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Gravité</th>
                <th>Équipement</th>
                <th>Site</th>
                <th>Description</th>
                <th>Source</th>
                <th>Apparue</th>
                <th>Corrigée</th>
              </tr>
            </thead>
            <tbody>
              {alerts.rows.map((row) => (
                <tr key={`${row.key}-${row.opened_at}`}>
                  <td><SeverityBadge severity={row.severity} /></td>
                  <td>{row.node_name ?? "—"}</td>
                  <td>{row.site ?? "—"}</td>
                  <td className="wrap">{row.message}</td>
                  <td>{toolLabel(row.tool)}</td>
                  <td className="num">
                    {dateTime(row.opened_at)}
                    {row.earlier ? " (antérieure)" : ""}
                  </td>
                  <td className="num">{row.closed_at ? dateTime(row.closed_at) : "non corrigée"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

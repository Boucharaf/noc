import { useState } from "react";
import { Link } from "react-router-dom";

import Panel from "../components/ui/Panel";
import SitesMap from "../components/domain/SitesMap";
import Stat from "../components/ui/Stat";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { availabilityColor } from "../lib/vocabulary";
import { duration, monthLabel, num, pct } from "../lib/format";
import { useKpiLocalities, useKpiLocalitiesMap, useLocalityNodes } from "../hooks/queries";
import { usePeriodStore } from "../store/ui";

/**
 * Carte des sites et drill-down géographique.
 *
 * Le panneau de droite change au clic sur un site : c'est le maillon
 * « KPI global → site → équipement » du drill-down demandé. Sans lui, la
 * carte n'est qu'une illustration — jolie, et sur laquelle on ne peut
 * rien faire.
 */
export default function MapPage() {
  const { month, year, previousMonth, nextMonth, goToCurrent } = usePeriodStore();
  const isCurrent = usePeriodStore((s) => s.isCurrentPeriod());
  const [selected, setSelected] = useState(null);

  const mapQuery = useKpiLocalitiesMap();
  const ranking = useKpiLocalities(50);
  const localityNodes = useLocalityNodes(selected?.locality_id);

  const items = mapQuery.data ?? [];
  const totals = items.reduce(
    (accumulator, locality) => ({
      incidents: accumulator.incidents + (locality.total_incidents ?? 0),
      critical: accumulator.critical + (locality.critical ?? 0),
      nodes: accumulator.nodes + (locality.nb_nodes ?? 0),
    }),
    { incidents: 0, critical: 0, nodes: 0 },
  );

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Carte des sites"
        subtitle="Répartition géographique des incidents et de la disponibilité"
        actions={
          <PeriodPicker
            month={month}
            year={year}
            label={monthLabel(month, year)}
            onPrevious={previousMonth}
            onNext={nextMonth}
            onCurrent={goToCurrent}
            isCurrent={isCurrent}
          />
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat label="Sites suivis" value={num(items.length, "0")} />
        <Stat label="Équipements" value={num(totals.nodes, "0")} />
        <Stat label="Incidents du mois" value={num(totals.incidents, "0")} />
        <Stat
          label="Dont critiques"
          value={num(totals.critical, "0")}
          color={totals.critical ? "var(--sev-critical)" : "var(--state-up)"}
        />
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 lg:col-span-8 min-w-0">
          <Panel title="Carte" flush>
            <QueryBoundary
              query={mapQuery}
              emptyMessage="Aucun site géolocalisé"
              emptyHint="Les coordonnées proviennent de dim_locality, peuplée par etl/scripts/discover_geography.py."
            >
              {(localities) => (
                <SitesMap localities={localities} height={480} onSelect={setSelected} />
              )}
            </QueryBoundary>
          </Panel>
        </div>

        <div className="col-span-12 lg:col-span-4 min-w-0">
          {selected ? (
            <Panel
              title={selected.locality}
              subtitle={selected.region}
              to={`/equipements?locality_id=${selected.locality_id}`}
              toLabel="Équipements"
              actions={
                <button type="button" className="btn btn-ghost btn-sm" onClick={() => setSelected(null)}>
                  Fermer
                </button>
              }
              flush
            >
              <div className="grid grid-cols-2 gap-2 p-2.5">
                <Stat
                  compact
                  label="Disponibilité"
                  value={pct(selected.availability_pct, 2)}
                  color={availabilityColor(selected.availability_pct)}
                />
                <Stat compact label="Incidents" value={num(selected.total_incidents, "0")} />
                <Stat
                  compact
                  label="Critiques"
                  value={num(selected.critical, "0")}
                  color={selected.critical ? "var(--sev-critical)" : "var(--state-up)"}
                />
                <Stat compact label="MTTR moyen" value={duration(selected.avg_mttr)} />
              </div>

              <QueryBoundary
                query={localityNodes}
                compact
                empty={(d) => !d?.nodes?.length}
                emptyMessage="Aucun équipement sur ce site ce mois"
              >
                {(data) => (
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Équipement</th>
                        <th style={{ textAlign: "right" }}>Inc.</th>
                        <th style={{ textAlign: "right" }}>Ouv.</th>
                        <th style={{ textAlign: "right" }}>Dispo.</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.nodes.map((node) => (
                        <tr key={node.node_id}>
                          <td>
                            <Link
                              to={`/equipements/${node.node_id}`}
                              style={{ color: "var(--ink)", textDecoration: "none" }}
                              className="hover:underline"
                            >
                              {node.name}
                            </Link>
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {num(node.total_incidents, "0")}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: node.open ? "var(--sev-medium)" : "var(--ink-3)",
                            }}
                          >
                            {num(node.open, "0")}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: availabilityColor(node.availability_pct),
                            }}
                          >
                            {pct(node.availability_pct, 1)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </QueryBoundary>
            </Panel>
          ) : (
            <Panel title="Classement des sites" subtitle="cliquez un site sur la carte" flush>
              <QueryBoundary query={ranking} compact emptyMessage="Aucun incident ce mois">
                {(localities) => (
                  <div style={{ maxHeight: 480, overflow: "auto" }}>
                    <table className="tbl">
                      <thead>
                        <tr>
                          <th>Site</th>
                          <th style={{ textAlign: "right" }}>Inc.</th>
                          <th style={{ textAlign: "right" }}>Crit.</th>
                          <th style={{ textAlign: "right" }}>Dispo.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {localities.map((locality) => (
                          <tr
                            key={locality.locality_id ?? locality.locality}
                            className="row-clickable"
                            onClick={() =>
                              setSelected(
                                items.find((item) => item.locality_id === locality.locality_id) ??
                                  locality,
                              )
                            }
                          >
                            <td>
                              {locality.locality}
                              <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                                {locality.region}
                              </span>
                            </td>
                            <td className="num" style={{ textAlign: "right" }}>
                              {num(locality.total_incidents, "0")}
                            </td>
                            <td
                              className="num"
                              style={{
                                textAlign: "right",
                                color: locality.critical ? "var(--sev-critical)" : "var(--ink-3)",
                              }}
                            >
                              {num(locality.critical, "0")}
                            </td>
                            <td
                              className="num"
                              style={{
                                textAlign: "right",
                                color: availabilityColor(locality.availability_pct),
                              }}
                            >
                              {pct(locality.availability_pct, 1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </QueryBoundary>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}

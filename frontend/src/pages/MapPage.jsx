import { useState } from "react";
import { Link } from "react-router-dom";

import Panel from "../components/ui/Panel";
import SitesMap from "../components/domain/SitesMap";
import Stat from "../components/ui/Stat";
import { NodeStateBadge } from "../components/ui/Badge";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { availabilityColor, toolLabel } from "../lib/vocabulary";
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
      alerts: accumulator.alerts + (locality.alerts ?? 0),
      down: accumulator.down + (locality.down ?? 0),
      nodes: accumulator.nodes + (locality.nb_nodes ?? 0),
    }),
    { alerts: 0, down: 0, nodes: 0 },
  );

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Carte des sites"
        subtitle="État courant des équipements et des alertes par site"
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
        <Stat
          label="Sites géolocalisés"
          value={num(items.filter((item) => item.latitude != null && item.longitude != null).length, "0")}
        />
        <Stat label="Équipements" value={num(totals.nodes, "0")} />
        <Stat label="Alertes actives" value={num(totals.alerts, "0")} />
        <Stat
          label="Équipements en panne"
          value={num(totals.down, "0")}
          color={totals.down ? "var(--sev-critical)" : "var(--state-up)"}
        />
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 lg:col-span-8 min-w-0">
          <Panel title="Carte" flush>
            <QueryBoundary
              query={mapQuery}
              emptyMessage="Aucun site géolocalisé"
              emptyHint="Seuls les sites pour lesquels une source fournit des coordonnées apparaissent sur la carte."
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
              subtitle={selected.region || "État courant du snapshot"}
              to={`/equipements?locality_id=${encodeURIComponent(selected.locality_id)}`}
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
                  label="Équipements"
                  value={num(selected.nodes, "0")}
                />
                <Stat compact label="Alertes actives" value={num(selected.alerts, "0")} />
                <Stat
                  compact
                  label="En panne"
                  value={num(selected.down, "0")}
                  color={selected.down ? "var(--sev-critical)" : "var(--state-up)"}
                />
                <Stat compact label="Dégradés" value={num(selected.degraded, "0")} />
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
                        <th>État</th>
                        <th style={{ textAlign: "right" }}>Alertes</th>
                        <th>Sources</th>
                      </tr>
                    </thead>
                    <tbody>
                        {data.nodes.map((node) => (
                        <tr key={node.id}>
                          <td>
                            <Link
                              to={`/equipements/${encodeURIComponent(node.id)}`}
                              style={{ color: "var(--ink)", textDecoration: "none" }}
                              className="hover:underline"
                            >
                              {node.name}
                            </Link>
                          </td>
                          <td>
                            <NodeStateBadge state={node.state} />
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {num(node.alerts, "0")}
                          </td>
                          <td>
                            {Object.keys(node.sources ?? {}).map(toolLabel).join(", ") || "—"}
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

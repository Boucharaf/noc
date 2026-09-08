import { useState } from "react";
import { Link } from "react-router-dom";
import { Download } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat, { Meter } from "../components/ui/Stat";
import SitesMap from "../components/domain/SitesMap";
import { BarChart, Donut, HourHeatmap, LineChart } from "../components/charts";
import { Notice } from "../components/ui/Controls";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { decimal, duration, monthLabel, num, pct } from "../lib/format";
import { availabilityColor, severityMeta } from "../lib/vocabulary";
import { errorMessage } from "../api/client";
import { report } from "../api/noc";
import { saveBlob } from "../lib/download";
import { usePeriodStore } from "../store/ui";
import { usePermission } from "../hooks/useSession";
import { PERMISSIONS } from "../lib/permissions";
import {
  useCoverage,
  useKpiCauses,
  useKpiHourDistribution,
  useKpiLocalities,
  useKpiLocalitiesMap,
  useKpiMinistries,
  useKpiRecurrent,
  useKpiSummary,
  useKpiTrend,
  useSla,
} from "../hooks/queries";

/**
 * Vue de direction — NIVEAU 1 du document métier
 * (« Disponibilité globale | Incidents critiques | SLA | MTTR |
 *   Top 10 sites | Tendance 1 mois »).
 *
 * Écran de PILOTAGE, pas d'exploitation : aucun bouton d'action sur un
 * incident n'y figure, et c'est délibéré. Un directeur qui acquitte une
 * alerte depuis son écran court-circuite la file du technicien sans que
 * personne ne le sache. Ici on lit des tendances, on compare à des
 * objectifs, on télécharge un rapport.
 *
 * Chaque indicateur est présenté AVEC sa cible et sa variation par
 * rapport au mois précédent. Un « MTTR : 5 h 20 » seul n'est pas
 * interprétable ; « 5 h 20, cible ≤ 4 h, +1 h 20 vs mois dernier » l'est.
 */
export default function DirectionView() {
  const { month, year, previousMonth, nextMonth, goToCurrent } = usePeriodStore();
  const isCurrent = usePeriodStore((s) => s.isCurrentPeriod());
  const canDownload = usePermission(PERMISSIONS.DOWNLOAD_REPORT);

  const summary = useKpiSummary();
  const sla = useSla();
  const trend = useKpiTrend(6);
  const localities = useKpiLocalities(10);
  const localitiesMap = useKpiLocalitiesMap();
  const ministries = useKpiMinistries();
  const causes = useKpiCauses();
  const hours = useKpiHourDistribution();
  const recurrent = useKpiRecurrent(3);
  const coverage = useCoverage();

  const [downloadError, setDownloadError] = useState(null);
  const [downloading, setDownloading] = useState(null);

  const kpi = summary.data?.kpi;
  const deltas = summary.data?.vs_previous_month;

  const download = async (format) => {
    setDownloadError(null);
    setDownloading(format);
    try {
      const blob = await report.monthly({ month, year, format });
      await saveBlob(blob, `rapport-noc-${year}-${String(month).padStart(2, "0")}.${format}`);
    } catch (error) {
      setDownloadError(error.message || errorMessage(error));
    } finally {
      setDownloading(null);
    }
  };

  const trendData = trend.data ?? [];

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Pilotage RESINA"
        subtitle="Synthèse mensuelle de la disponibilité, des incidents et des engagements de service"
        actions={
          <>
            <PeriodPicker
              month={month}
              year={year}
              label={monthLabel(month, year)}
              onPrevious={previousMonth}
              onNext={nextMonth}
              onCurrent={goToCurrent}
              isCurrent={isCurrent}
            />
            {canDownload && (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={downloading !== null}
                  onClick={() => download("pdf")}
                >
                  <Download size={13} /> {downloading === "pdf" ? "…" : "PDF"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={downloading !== null}
                  onClick={() => download("docx")}
                >
                  {downloading === "docx" ? "…" : "DOCX"}
                </button>
              </div>
            )}
          </>
        }
      />

      {downloadError && (
        <Notice tone="error" onClose={() => setDownloadError(null)}>
          {downloadError}
        </Notice>
      )}

      {isCurrent && (
        <p className="text-[11px]" style={{ color: "var(--ink-3)" }}>
          Mois en cours : les valeurs évoluent jusqu'à la clôture. La disponibilité est
          rapportée au temps réellement écoulé, pas au mois entier.
        </p>
      )}

      {/* --- Indicateurs de direction --- */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          label="Disponibilité réseau"
          value={pct(kpi?.network_availability_pct, 2)}
          color={availabilityColor(kpi?.network_availability_pct)}
          target="≥ 99 %"
          delta={deltas?.availability_delta}
          deltaLabel="points vs mois précédent"
        />
        <Stat
          label="Incidents"
          value={num(kpi?.total_incidents)}
          delta={deltas?.incidents_delta}
          invertDelta
          deltaLabel="vs mois précédent"
          to="/incidents"
        />
        <Stat
          label="Incidents critiques"
          value={num(kpi?.critical)}
          color={kpi?.critical > 5 ? "var(--sev-critical)" : "var(--ink)"}
          target="≤ 5"
          to="/incidents?severity=critical"
        />
        <Stat
          label="Taux de résolution"
          value={pct(kpi?.resolution_rate_pct, 1)}
          color={
            kpi?.resolution_rate_pct >= 95 ? "var(--state-up)" : "var(--sev-medium)"
          }
          target="≥ 95 %"
        />
        <Stat
          label="MTTR moyen"
          value={duration(kpi?.avg_mttr_minutes)}
          color={kpi?.avg_mttr_minutes > 240 ? "var(--sev-high)" : "var(--state-up)"}
          target="≤ 4 h"
        />
        <Stat
          label="MTTA moyen"
          value={duration(kpi?.avg_mtta_minutes)}
          color={kpi?.avg_mtta_minutes > 15 ? "var(--sev-medium)" : "var(--state-up)"}
          target="≤ 15 min"
        />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          label="Respect des SLA"
          value={pct(sla.data?.global_compliance_pct, 1)}
          color={
            sla.data?.global_compliance_pct >= 95 ? "var(--state-up)" : "var(--sev-high)"
          }
          target="≥ 95 %"
          to="/sla"
        />
        <Stat
          label="SLA non tenus"
          value={num(sla.data?.total_breached, "0")}
          color={sla.data?.total_breached ? "var(--sev-critical)" : "var(--state-up)"}
          to="/sla"
        />
        <Stat
          label="Incidents ouverts"
          value={num(kpi?.open)}
          color={kpi?.open ? "var(--sev-medium)" : "var(--state-up)"}
        />
        <Stat
          label="Sites critiques"
          value={num(kpi?.critical_localities)}
          hint="≥ 1 incident critique"
        />
        <Stat
          label="Équip. récurrents"
          value={num(kpi?.recurrent_nodes)}
          color={kpi?.recurrent_nodes > 10 ? "var(--sev-high)" : "var(--ink)"}
          target="≤ 10 / mois"
        />
        <Stat
          label="Hors heures ouvrées"
          value={num(kpi?.off_hours_detected)}
          hint="détectés hors 6 h – 21 h"
        />
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Tendance --- */}
        <div className="col-span-12 xl:col-span-8 min-w-0">
          <Panel
            title="Tendance sur 6 mois"
            subtitle="volume d'incidents et disponibilité"
          >
            <QueryBoundary query={trend} compact emptyMessage="Pas d'historique disponible">
              <LineChart
                height={210}
                labels={trendData.map((point) => point.label)}
                legend
                series={[
                  {
                    label: "Incidents",
                    data: trendData.map((point) => point.total_incidents),
                    color: "var(--sev-high)",
                    fill: true,
                  },
                  {
                    label: "Résolus",
                    data: trendData.map((point) => point.resolved),
                    color: "var(--state-up)",
                  },
                ]}
              />
              <div className="mt-2">
                <LineChart
                  height={110}
                  labels={trendData.map((point) => point.label)}
                  yMin={90}
                  yMax={100}
                  targetLine={99}
                  valueFormatter={(value) => `${decimal(value, 1)} %`}
                  series={[
                    {
                      label: "Disponibilité",
                      data: trendData.map((point) => point.availability_pct),
                      color: "var(--accent)",
                      fill: true,
                    },
                  ]}
                />
              </div>
            </QueryBoundary>
          </Panel>
        </div>

        {/* --- Causes --- */}
        <div className="col-span-12 sm:col-span-6 xl:col-span-4">
          <Panel title="Causes des incidents" subtitle="part du volume mensuel">
            <QueryBoundary query={causes} compact emptyMessage="Aucune cause qualifiée">
              {(items) => (
                <div className="space-y-1">
                  {items.slice(0, 8).map((cause, index) => (
                    <div key={cause.category}>
                      <div className="flex items-baseline gap-2 text-[11.5px]">
                        <span className="flex-1 truncate" title={cause.label}>
                          {cause.label || cause.category}
                        </span>
                        <span className="num" style={{ color: "var(--ink-3)" }}>
                          {num(cause.total_incidents)}
                        </span>
                        <span className="num" style={{ width: 44, textAlign: "right" }}>
                          {pct(cause.share_pct, 1)}
                        </span>
                      </div>
                      <Meter
                        value={cause.share_pct}
                        max={100}
                        height={3}
                        // Dégradé d'une seule teinte plutôt qu'une couleur
                        // par cause : ce sont des parts d'un même total,
                        // pas des catégories à opposer.
                        color={`color-mix(in srgb, var(--accent) ${Math.max(30, 100 - index * 10)}%, var(--ink-3))`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Top 10 sites --- */}
        <div className="col-span-12 lg:col-span-7 min-w-0">
          <Panel title="Top 10 des sites les plus incidentés" flush to="/carte" toLabel="Carte">
            <QueryBoundary query={localities} compact emptyMessage="Aucun incident ce mois">
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}>#</th>
                      <th>Site</th>
                      <th>Région</th>
                      <th style={{ textAlign: "right" }}>Incidents</th>
                      <th style={{ textAlign: "right" }}>Critiques</th>
                      <th style={{ textAlign: "right" }}>MTTR</th>
                      <th style={{ textAlign: "right" }}>Dispo.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((locality, index) => (
                      <tr key={locality.locality_id ?? locality.locality}>
                        <td className="num" style={{ color: "var(--ink-3)" }}>
                          {index + 1}
                        </td>
                        <td>
                          <Link
                            to={`/equipements?locality_id=${locality.locality_id}`}
                            style={{ color: "var(--ink)", textDecoration: "none" }}
                            className="hover:underline"
                          >
                            {locality.locality}
                          </Link>
                        </td>
                        <td style={{ color: "var(--ink-3)" }}>{locality.region || "—"}</td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {num(locality.total_incidents)}
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
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                          {duration(locality.avg_mttr)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: availabilityColor(locality.availability_pct),
                          }}
                        >
                          {pct(locality.availability_pct, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </Panel>
        </div>

        {/* --- Ministères --- */}
        <div className="col-span-12 lg:col-span-5 min-w-0">
          <Panel title="Par ministère / structure" flush>
            <QueryBoundary
              query={ministries}
              compact
              emptyMessage="Aucun ministère rattaché"
              emptyHint="dim_ministry n'est peuplée que par etl/scripts/discover_geography.py — tant qu'il n'a pas tourné, ce classement reste vide."
            >
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Ministère</th>
                      <th style={{ textAlign: "right" }}>Équip.</th>
                      <th style={{ textAlign: "right" }}>Incidents</th>
                      <th style={{ textAlign: "right" }}>Critiques</th>
                      <th style={{ textAlign: "right" }}>MTTR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.slice(0, 12).map((ministry) => (
                      <tr key={ministry.ministry_id}>
                        <td className="truncate-cell" title={ministry.ministry}>
                          {ministry.ministry}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                          {num(ministry.nb_nodes)}
                        </td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {num(ministry.total_incidents)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: ministry.critical ? "var(--sev-critical)" : "var(--ink-3)",
                          }}
                        >
                          {num(ministry.critical, "0")}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                          {duration(ministry.avg_mttr)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Carte --- */}
        <div className="col-span-12 xl:col-span-7 min-w-0">
          <Panel title="Répartition géographique" flush>
            <QueryBoundary
              query={localitiesMap}
              compact
              emptyMessage="Aucun site géolocalisé"
              emptyHint="Les coordonnées viennent de dim_locality, peuplée par le script de découverte géographique de l'ETL."
            >
              {(items) => <SitesMap localities={items} height={360} />}
            </QueryBoundary>
          </Panel>
        </div>

        <div className="col-span-12 xl:col-span-5 space-y-2.5">
          {/* --- Couverture de supervision --- */}
          <Panel title="Couverture de supervision" to="/integrations" toLabel="Détail">
            <QueryBoundary query={coverage} compact empty={(d) => !d}>
              {(data) => (
                <>
                  <div className="flex items-center gap-3">
                    <Donut
                      size={96}
                      thickness={11}
                      segments={[
                        {
                          key: "monitored",
                          label: "Supervisés",
                          value: data.monitored_assets,
                          color: "var(--state-up)",
                        },
                        {
                          key: "unmonitored",
                          label: "Non supervisés",
                          value: data.unmonitored_assets,
                          color: "var(--sev-high)",
                        },
                      ]}
                      centerValue={pct(data.coverage_pct, 0)}
                      centerLabel="couvert"
                    />
                    <div className="flex-1 text-[11.5px] space-y-1">
                      <div className="flex justify-between">
                        <span style={{ color: "var(--ink-2)" }}>Parc total</span>
                        <span className="num">{num(data.total_assets)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span style={{ color: "var(--ink-2)" }}>Supervisés</span>
                        <span className="num" style={{ color: "var(--state-up)" }}>
                          {num(data.monitored_assets)}
                        </span>
                      </div>
                      <div className="flex justify-between">
                        <span style={{ color: "var(--ink-2)" }}>Non supervisés</span>
                        <span className="num" style={{ color: "var(--sev-high)" }}>
                          {num(data.unmonitored_assets)}
                        </span>
                      </div>
                    </div>
                  </div>
                  {!data.is_complete_inventory && (
                    <p className="text-[10.5px] mt-2" style={{ color: "var(--sev-medium)" }}>
                      Le parc de référence est celui que les outils remontent : ce taux
                      restera proche de 100 % tant qu'un inventaire théorique complet
                      (CMDB iTop) n'alimentera pas la base.
                    </p>
                  )}
                </>
              )}
            </QueryBoundary>
          </Panel>

          {/* --- Distribution horaire --- */}
          <Panel
            title="Heures de survenue"
            subtitle="dimensionnement des équipes"
          >
            <QueryBoundary query={hours} compact emptyMessage="Aucun incident ce mois">
              {(items) => <HourHeatmap data={items} />}
            </QueryBoundary>
          </Panel>

          {/* --- Équipements récurrents --- */}
          <Panel title="Équipements récurrents" flush>
            <QueryBoundary
              query={recurrent}
              compact
              emptyMessage="Aucun équipement en panne répétée"
              emptyHint="Seuil : au moins 3 incidents sur le mois."
            >
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Équipement</th>
                      <th>Site</th>
                      <th style={{ textAlign: "right" }}>Incidents</th>
                      <th>Cause principale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.slice(0, 8).map((node) => (
                      <tr key={node.node_id ?? node.code}>
                        <td>
                          {node.node_id ? (
                            <Link
                              to={`/equipements/${node.node_id}`}
                              style={{ color: "var(--ink)", textDecoration: "none" }}
                              className="hover:underline"
                            >
                              {node.name}
                            </Link>
                          ) : (
                            node.name
                          )}
                        </td>
                        <td style={{ color: "var(--ink-3)" }}>{node.locality}</td>
                        <td className="num" style={{ textAlign: "right", color: "var(--sev-high)" }}>
                          {num(node.total_incidents)}
                        </td>
                        <td style={{ color: "var(--ink-2)" }}>{node.main_cause || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      {/* --- Comparaison des gravités du mois --- */}
      <Panel title="Engagements de service par gravité" to="/sla" toLabel="Détail SLA" flush>
        <QueryBoundary query={sla} compact empty={(d) => !d?.by_severity?.length}>
          {(data) => (
            <div className="p-2.5">
              <BarChart
                height={150}
                horizontal
                labels={data.by_severity.map((row) => severityMeta(row.severity).label)}
                valueFormatter={(value) => `${decimal(value, 0)} %`}
                series={[
                  {
                    label: "Respect du délai de résolution",
                    data: data.by_severity.map((row) => row.ttr_compliance_pct ?? 0),
                    colors: data.by_severity.map((row) =>
                      (row.ttr_compliance_pct ?? 0) >= 95
                        ? "var(--state-up)"
                        : (row.ttr_compliance_pct ?? 0) >= 80
                          ? "var(--sev-medium)"
                          : "var(--sev-critical)",
                    ),
                  },
                ]}
              />
            </div>
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

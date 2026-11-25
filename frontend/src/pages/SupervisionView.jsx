import { useState } from "react";

import { useWindowStore, windowDays, windowLabel } from "../store/ui";
import { Link } from "react-router-dom";

import AlertDrawer from "../components/domain/AlertDrawer";
import DataQuality from "../components/domain/DataQuality";
import { helpFor } from "../lib/glossary";
import IncidentTable from "../components/domain/IncidentTable";
import KpiRow from "../components/domain/KpiRow";
import SlaAtRisk from "../components/domain/SlaAtRisk";
import { DashboardSummary, FleetStatesChart } from "../components/domain/FleetInsights";
import Panel from "../components/ui/Panel";
import { StackedBar } from "../components/ui/Stat";
import { Donut, LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { FilterSelect } from "../components/ui/Controls";
import { NodeStateBadge, SeverityBadge, ToolStateBadge } from "../components/ui/Badge";
import { decimal, num, plural, time, availabilityPct } from "../lib/format";
import { availabilityColor, nodeTypeLabel, toolLabel, metricMeta, METRIC_TYPES } from "../lib/vocabulary";
import {
  useAlertSummary,
  useAlerts,
  useInterop,
  useKpiLocalities,
  useMaintenanceWindows,
  useNetworkSeries,
  useNodeCoverage,
  useNodeStates,
  useNodes,
  useOpenAlerts,
  useTopNodes,
} from "../hooks/queries";

/**
 * Salle de supervision — NIVEAU 2 du document métier
 * (« État du réseau | Incidents en cours | Alertes | Performance |
 *   Équipements critiques »).
 *
 * Écran du Chef NOC. Sa différence avec la console du technicien n'est
 * pas cosmétique : le technicien traite des lignes, le chef de salle
 * répartit la charge et arbitre. On y trouve donc deux blocs qui
 * n'existent nulle part ailleurs — la CHARGE PAR INTERVENANT (avec la
 * ligne « non affecté » en tête, qui est la vraie alerte de management)
 * et la SANTÉ DE LA COLLECTE, parce qu'un connecteur muet rend faux tout
 * le reste de l'écran sans qu'aucun compteur ne bouge.
 *
 * S'y ajoutent les incidents iTop en danger de SLA (le seul engagement sur
 * lequel la salle peut encore agir), les équipements les plus alertants et
 * l'heure d'apparition des alertes, qui sert à dimensionner l'astreinte.
 */

const DAY_MS = 86_400_000;

/** État d'un outil, dans le vocabulaire de ToolStateBadge. */
function toolState(tool) {
  if (tool.not_configured) return "not_configured";
  if (tool.never_collected) return "unknown";
  if (!tool.reachable) return "error";
  return tool.stale ? "stale" : "ok";
}

const STATE_WEIGHT = { down: 3, degraded: 2, unknown: 1, silent: 1 };
const SEVERITY_WEIGHT = { critical: 5, high: 4, medium: 3, low: 2, info: 1 };

/** Équipements en panne ∪ les plus alertants, triés par urgence, 8 au plus. */
function mergeToTreat(down = [], alerting = []) {
  const byId = new Map();
  for (const node of [...(down ?? []), ...(alerting ?? [])]) {
    if (!node?.node_id) continue;
    if (node.state !== "down" && !node.alerts) continue;
    byId.set(node.node_id, { ...byId.get(node.node_id), ...node });
  }
  const urgency = (node) =>
    (STATE_WEIGHT[node.state] ?? 0) * 100 +
    (node.alerts ? SEVERITY_WEIGHT[node.worst_severity] ?? 0 : 0) * 10 +
    Math.min(9, node.alerts ?? 0);
  return [...byId.values()].sort((a, b) => urgency(b) - urgency(a)).slice(0, 8);
}

export default function SupervisionView() {
  // Période et filtres viennent de la barre unique (AM-30) : la page n'a
  // plus de sélecteur propre, et organisation / type s'appliquent à TOUS
  // les blocs par le périmètre commun (useScopeParams).
  const hours = useWindowStore((s) => s.hours);
  const [metric, setMetric] = useState("availability_pct");
  const [selectedId, setSelectedId] = useState(null);


  const summary = useAlertSummary();
  const nodeStates = useNodeStates();
  const series = useNetworkSeries({ metricType: metric, hours });
  const alertsQuery = useOpenAlerts({ limit: 40, kind: "technical" });
  const allAlerts = useAlerts({ limit: 1000, kind: "technical", confirmed: true });
  const interop = useInterop();
  const coverage = useNodeCoverage();
  const maintenance = useMaintenanceWindows("active");
  const localities = useKpiLocalities({ limit: 8, days: windowDays(hours) });
  const topNodes = useTopNodes(8);
  const criticalNodes = useNodes({ state: "down", limit: 8, sort: "state" });
  // INC-16 : une seule liste « à traiter », sans doublon entre les équipements
  // en panne et les plus alertants.
  const toTreat = mergeToTreat(criticalNodes.data?.items, topNodes.data);

  const s = summary.data;
  const states = nodeStates.data;

  // « > 24 h » se lit sur la liste des alertes déjà chargée.
  const openAlerts = (allAlerts.data?.alerts ?? []).filter((alert) => !alert.resolved_at);
  const ageing = openAlerts.filter(
    (alert) => alert.since && Date.now() - Date.parse(alert.since) > DAY_MS,
  ).length;

  const nodesByTool = Object.fromEntries(
    (coverage.data ?? []).map((row) => [row.tool, row.nodes]),
  );
  const tools = (interop.data?.tools ?? []).map((tool) => ({
    ...tool,
    state: toolState(tool),
    nodes_supervised: nodesByTool[tool.tool],
  }));
  const toolsHealthy = tools.filter((tool) => tool.state === "ok").length;

  const severitySegments = [
    { key: "critical", label: "Critiques", value: s?.critical ?? 0, color: "var(--sev-critical)" },
    { key: "high", label: "Majeures", value: s?.high ?? 0, color: "var(--sev-high)" },
    { key: "medium", label: "Moyennes", value: s?.medium ?? 0, color: "var(--sev-medium)" },
    { key: "low", label: "Mineures", value: s?.low ?? 0, color: "var(--sev-low)" },
  ];

  const stateSegments = [
    { key: "down", label: "Hors service", value: states?.down, color: "var(--state-down)" },
    { key: "degraded", label: "Perturbés", value: states?.degraded ?? 0, color: "var(--state-degraded)" },
    { key: "unknown", label: "Inconnus", value: (states?.unknown ?? 0) + (states?.silent ?? 0), color: "var(--ink-3)" },
    { key: "maintenance", label: "Maintenance", value: states?.maintenance ?? 0, color: "var(--state-maintenance)" },
    { key: "up", label: "Normaux", value: states?.up, color: "var(--state-up)" },
  ];


  const seriesData = series.data?.points ?? [];
  const metricLabels = seriesData.map((point) => time(point.time));

  return (
    <div className="space-y-3.5">
      <PageHeader
        title="Salle de supervision"
        subtitle={`État du réseau, charge de l'équipe et santé de la collecte · période ${windowLabel(hours)}`}
      />

      {/* Z1 — bandeau de situation */}
      <DashboardSummary />

      {/* Z2 — les 6 indicateurs clés (AM-02, AM-03, AM-04). Les mesures
          réseau détaillées (latence, pertes, CPU…) sont sur Performance. */}
      <KpiRow />

      {/* Z3 — tendance (8 col) et parc par statut (4 col) */}
      <div className="grid grid-cols-12 gap-3.5">
        <div className="col-span-12 xl:col-span-8 min-w-0">
          <Panel
            title="Tendance réseau"
            scope={{ period: "window" }}
            sources="metrics"
            subtitle={`moyenne sur ${series.data?.contributing_nodes ?? 0} équipement(s) mesuré(s)`}
            to="/performance"
            toLabel="Analyser"
            actions={
              <FilterSelect
                ariaLabel="Métrique affichée"
                value={metric}
                onChange={setMetric}
                options={METRIC_TYPES.map(type => ({ value: type, label: metricMeta(type).label }))}
                width={150}
              />
            }
          >
            <QueryBoundary
              query={series}
              compact
              minHeight={196}
        empty={(data) => !data?.points?.length}
              emptyMessage="Non mesuré sur cette période"
              // AM-23 / INC-05 : un état vide dit sa cause et quoi faire.
              emptyHint={`Aucun outil branché (Zabbix, Centreon) ne publie « ${metricMeta(metric).label} » pour ce périmètre sur ${windowLabel(hours)}. Vérifiez l'écran Collecte, ou choisissez une autre mesure.`}
            >
              <LineChart
                exportName={`tendance-${metric}-${hours}h`}
                labels={metricLabels}
                height={196}
                yMax={metricMeta(metric).unit === "%" ? 100 : undefined}
                targetLine={metricMeta(metric).target}
                valueFormatter={(value) =>
                  `${value} ${metricMeta(metric).unit}`
                }
                series={[
                  {
                    label: metricMeta(metric).label,
                    data: seriesData.map((point) => point.value),
                    pointCounts: seriesData.map((point) => point.nb_nodes),
                    color: metricMeta(metric).color ?? "var(--accent)",
                    fill: true,
                  },
                ]}
              />
            </QueryBoundary>
          </Panel>
        </div>
        <div className="col-span-12 xl:col-span-4 min-w-0">
          <Panel title="Parc supervisé" to="/equipements" scope={{ period: "live" }} sources="fleet">
            <div className="flex items-center gap-5">
              <Donut
                size={150}
                thickness={20}
                segments={stateSegments}
                centerValue={num(states?.total, "0")}
                centerLabel="équip."
              />
              <ul className="flex-1 space-y-1 min-w-0">
                {stateSegments.map((segment) => (
                  <li key={segment.key} className="flex items-center gap-2 text-[14px] py-0.5">
                    <span className="dot" style={{ background: segment.color }} />
                    <span className="flex-1 truncate" style={{ color: "var(--ink-2)" }}>
                      {segment.label}
                    </span>
                    <span className="num font-semibold">{num(segment.value, "0")}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>

        </div>
      </div>

      {/* Z4 — alertes à traiter (7 col) · Z5 — SLA en danger (5 col) */}
      <div className="grid grid-cols-12 gap-3.5 items-start">
        <div className="col-span-12 xl:col-span-7 min-w-0">
          <Panel
            title="Alertes en cours"
            scope={{ period: "live" }}
            accent="var(--sev-high)"
            to="/alertes"
            toLabel="Toute la file"
            flush
          >
            <QueryBoundary
              query={alertsQuery}
              skeleton={<SkeletonRows rows={5} columns={6} />}
              emptyMessage="Aucune alerte ouverte"
            >
              {(items) => (
                <IncidentTable
                  incidents={items.slice(0, 8)}
                  selectedId={selectedId}
                  onSelect={(row) => setSelectedId(row.id)}
                />
              )}
            </QueryBoundary>
          </Panel>
        </div>
        <div className="col-span-12 xl:col-span-5 min-w-0 space-y-3.5">
          <SlaAtRisk limit={6} />
          <Panel title="Alertes ouvertes" scope={{ period: "live" }} sources="alerts">
            <div className="flex items-baseline gap-2 mb-1.5">
              <span className="stat-value" style={{ fontSize: 32 }}>
                {num(s?.total_open, "0")}
              </span>
              <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                sur {plural(s?.localities_affected ?? 0, "site touché")}
              </span>
            </div>
            <StackedBar segments={severitySegments} height={7} />
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-2 text-[12px]">
              {severitySegments.map((segment) => (
                <div key={segment.key} className="flex items-center gap-1.5">
                  <span className="dot" style={{ background: segment.color }} />
                  <span style={{ color: "var(--ink-2)" }}>{segment.label}</span>
                  <span className="num ml-auto">{num(segment.value, "0")}</span>
                </div>
              ))}
            </div>
            <div
              className="grid grid-cols-2 gap-2 mt-2.5 pt-2 border-t"
              style={{ borderColor: "var(--border)" }}
            >
              <MiniStat
                label="Non acquittés"
                value={num(s?.unacknowledged, "0")}
                color={s?.unacknowledged ? "var(--sev-medium)" : "var(--state-up)"}
              />
              <MiniStat
                label="> 24 h"
                value={num(ageing, "0")}
                color={ageing ? "var(--sev-critical)" : "var(--state-up)"}
              />
            </div>
          </Panel>
        </div>
      </div>

      {/* Z6 — sources et qualité des données (4 col) · Z7 — équipements à
          traiter (8 col, INC-16 : fusion « HS » et « les plus alertants ») */}
      <div className="grid grid-cols-12 gap-3.5 items-start">
        <div className="col-span-12 lg:col-span-4 min-w-0 space-y-3.5">
          <Panel
            title="Collecte ETL"
            subtitle={interop.data ? `${toolsHealthy}/${tools.length} actifs` : undefined}
            to="/integrations"
            flush
          >
            <QueryBoundary query={interop} compact empty={(d) => !d?.tools?.length}>
              {() => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {tools.map((tool) => (
                    <li key={tool.tool} className="flex items-center gap-2 px-2.5 py-1.5">
                      <span className="text-[12px] font-medium flex-1">
                        {toolLabel(tool.tool)}
                      </span>
                      <span className="num text-[12px]" style={{ color: "var(--ink-3)" }}>
                        {tool.nodes_supervised ? `${tool.nodes_supervised} éq.` : ""}
                      </span>
                      <ToolStateBadge state={tool.state} />
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Panel>
          <DataQuality />
        </div>
        <div className="col-span-12 lg:col-span-8 min-w-0">
          <Panel
            title="Équipements à traiter"
            scope={{ period: "live" }}
            subtitle="en panne ou en alerte · les plus urgents d'abord"
            accent="var(--state-down)"
            to="/equipements?state=down"
            flush
            sources="fleet"
          >
            <QueryBoundary
              query={criticalNodes.isLoading ? criticalNodes : topNodes}
              compact
              empty={() => toTreat.length === 0}
              emptyMessage="Aucun équipement en panne ni en alerte"
            >
              {() => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {toTreat.map((node) => (
                    <li key={node.node_id}>
                      <Link
                        to={`/equipements/${encodeURIComponent(node.node_id)}`}
                        className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-2)]"
                        style={{ textDecoration: "none", color: "inherit" }}
                      >
                        <NodeStateBadge state={node.state} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] truncate font-medium">{node.name}</span>
                          <span className="block text-[12px]" style={{ color: "var(--ink-3)" }}>
                            {node.locality || "site inconnu"} · {nodeTypeLabel(node.node_type) || "type inconnu"}
                          </span>
                        </span>
                        {node.worst_severity && node.alerts > 0 && (
                          <SeverityBadge severity={node.worst_severity} short />
                        )}
                        <span className="num text-[12px]" style={{ minWidth: 58, textAlign: "right" }}>
                          {node.alerts ? `${node.alerts} alerte${node.alerts > 1 ? "s" : ""}` : "—"}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      {/* Sous le premier écran : le détail */}
      <FleetStatesChart height={170} />

      <div className="grid grid-cols-12 gap-3.5 items-start">
        <div className="col-span-12 xl:col-span-7 min-w-0">
          <Panel
            title="Sites les plus touchés"
            scope={{ period: "window", territorial: true }}
            subtitle="moyennes journalières des agrégats de collecte"
            to="/territoire"
            toLabel="Territoire"
            flush
          >
            <QueryBoundary query={localities} compact emptyMessage="Aucun incident ce mois">
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Site</th>
                      <th style={{ textAlign: "right" }}>Alertes actives (moy.)</th>
                      <th style={{ textAlign: "right" }}>Critiques (moy.)</th>
                      <th style={{ textAlign: "right" }}>En panne (moy.)</th>
                      <th style={{ textAlign: "right" }}>Dispo.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((locality) => (
                      <tr key={locality.locality_id ?? locality.locality}>
                        <td>
                          <Link
                            to={`/equipements?site=${encodeURIComponent(locality.locality ?? "")}`}
                            style={{ color: "var(--ink)", textDecoration: "none" }}
                            className="hover:underline"
                          >
                            {locality.locality}
                          </Link>
                        </td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {decimal(locality.average_alerts, 1)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: locality.critical ? "var(--sev-critical)" : "var(--ink-3)",
                          }}
                        >
                          {decimal(locality.critical, 1, "0")}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                          {decimal(locality.avg_down, 1, "0")}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: availabilityColor(locality.availability_pct),
                          }}
                        >
                          {availabilityPct(locality.availability_pct, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </Panel>
        </div>
        <div className="col-span-12 xl:col-span-5 min-w-0">
          <Panel
            title="Maintenances en cours"
            accent="var(--state-maintenance)"
            to="/maintenances"
            flush
          >
            <QueryBoundary
              query={maintenance}
              compact
              empty={(d) => !d?.windows?.length}
              emptyMessage="Aucune maintenance en cours"
              emptyHint="Planifiées dans iTop (changements) ou Zabbix, elles apparaissent ici."
            >
              {(data) => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {data.windows.slice(0, 6).map((window) => (
                    <li key={window.key} className="px-2.5 py-1.5">
                      <div className="text-[12px] truncate">
                        {window.kind === "change" && window.ref ? `${window.ref} · ` : ""}
                        {window.title}
                      </div>
                      <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                        {window.nodes_total
                          ? `${num(window.nodes_total)} équipement(s)${window.sites?.[0] ? ` · ${window.sites[0]}` : ""}`
                          : "aucun équipement retrouvé"}{" "}
                        · jusqu'à <span className="num">{window.end ? time(window.end) : "—"}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <AlertDrawer
        alertKey={selectedId}
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
      />
    </div>
  );
}

function MiniStat({ label, value, color }) {
  return (
    <div title={helpFor(label)} className={helpFor(label) ? "cursor-help" : undefined}>
      <div className="stat-value text-[24px]" style={{ color }}>
        {value}
      </div>
      <div className="text-[12px] uppercase tracking-[0.06em]" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
    </div>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";

import AlertDrawer from "../components/domain/AlertDrawer";
import IncidentTable from "../components/domain/IncidentTable";
import NetworkVitals from "../components/domain/NetworkVitals";
import SlaAtRisk from "../components/domain/SlaAtRisk";
import { DashboardSummary, FleetStatesChart } from "../components/domain/FleetInsights";
import Panel from "../components/ui/Panel";
import { StackedBar } from "../components/ui/Stat";
import { Donut, HourHeatmap, LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { FilterSelect, Segmented, Toolbar } from "../components/ui/Controls";
import { NodeStateBadge, SeverityBadge, ToolStateBadge } from "../components/ui/Badge";
import { decimal, num, pct, time } from "../lib/format";
import { availabilityColor, toolLabel, metricMeta, METRIC_TYPES } from "../lib/vocabulary";
import {
  useAlertSummary,
  useAlerts,
  useHourDistribution,
  useInterop,
  useKpiLocalities,
  useMaintenanceWindows,
  useNetworkKpi,
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

const WINDOWS = [
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 72, label: "3 j" },
  { value: 168, label: "7 j" },
];

const DAY_MS = 86_400_000;

/** État d'un outil, dans le vocabulaire de ToolStateBadge. */
function toolState(tool) {
  if (tool.not_configured) return "not_configured";
  if (tool.never_collected) return "unknown";
  if (!tool.reachable) return "error";
  return tool.stale ? "stale" : "ok";
}

export default function SupervisionView() {
  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState("availability_pct");
  const [organisation, setOrganisation] = useState(null);
  const [nodeType, setNodeType] = useState(null);
  const [selectedId, setSelectedId] = useState(null);


  const summary = useAlertSummary();
  const nodeStates = useNodeStates();
  const network = useNetworkKpi({ hours });
  const series = useNetworkSeries({ metricType: metric, hours });
  const alertsQuery = useOpenAlerts({
    limit: 40,
    organisation,
    node_type: nodeType,
    kind: "technical",
  });
  const allAlerts = useAlerts({
    limit: 1000,
    organisation,
    node_type: nodeType,
    kind: "technical",
  });
  const interop = useInterop();
  const coverage = useNodeCoverage();
  const maintenance = useMaintenanceWindows("active");
  const localities = useKpiLocalities({ limit: 8 });
  const topNodes = useTopNodes(8);
  const hours24 = useHourDistribution();
  const criticalNodes = useNodes({ state: "down", limit: 8, sort: "state", organisation, node_type: nodeType });

  const allNodesQuery = useNodes({ limit: 2000 });
  const allNodes = allNodesQuery.data?.items ?? [];
  const orgOptions = [...new Set(allNodes.map(n => n.organisation).filter(Boolean))].map(o => ({ value: o, label: o }));
  const typeOptions = [...new Set(allNodes.map(n => n.node_type).filter(Boolean))].map(t => ({ value: t, label: t }));

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
    { key: "high", label: "Majeurs", value: s?.high ?? 0, color: "var(--sev-high)" },
    { key: "medium", label: "Moyens", value: s?.medium ?? 0, color: "var(--sev-medium)" },
    { key: "low", label: "Mineurs", value: s?.low ?? 0, color: "var(--sev-low)" },
  ];

  const stateSegments = [
    { key: "down", label: "Hors service", value: states?.down, color: "var(--state-down)" },
    { key: "degraded", label: "Perturbés", value: states?.degraded ?? 0, color: "var(--state-degraded)" },
    { key: "unknown", label: "Inconnus", value: (states?.unknown ?? 0) + (states?.silent ?? 0), color: "var(--ink-3)" },
    { key: "maintenance", label: "Maintenance", value: states?.maintenance ?? 0, color: "var(--state-maintenance)" },
    { key: "up", label: "Normaux", value: states?.up, color: "var(--state-up)" },
  ];

  const hourRows = hours24.data ?? [];
  const hourTotal = hourRows.reduce((sum, row) => sum + row.count, 0);
  const offHours = hourRows.filter((row) => row.off_hours).reduce((sum, row) => sum + row.count, 0);

  const seriesData = series.data?.points ?? [];
  const metricLabels = seriesData.map((point) => time(point.time));

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Salle de supervision"
        subtitle="État du réseau, charge de l'équipe et santé de la collecte"
        actions={
          <Toolbar>
            {orgOptions.length > 0 && (
              <FilterSelect
                label="Organisation"
                value={organisation}
                onChange={setOrganisation}
                allLabel="Toutes"
                width={160}
                options={orgOptions}
              />
            )}
            {typeOptions.length > 0 && (
              <FilterSelect
                label="Type"
                value={nodeType}
                onChange={setNodeType}
                allLabel="Tous types"
                width={140}
                options={typeOptions}
              />
            )}
            <Segmented
              ariaLabel="Fenêtre d'observation"
              value={hours}
              onChange={setHours}
              options={WINDOWS}
            />
          </Toolbar>
        }
      />

      <DashboardSummary />

      {/* Colonnes auto-ajustées : le nombre de tuiles dépend des mesures
          réellement collectées, la rangée ne doit pas rester à moitié vide. */}
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        <NetworkVitals data={network.data} expectedNodes={states?.total} compact />
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Courbe réseau --- */}
        <div className="col-span-12 xl:col-span-8 min-w-0">
          <Panel
            title="Tendance réseau"
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
              empty={(data) => !data?.points?.length}
              emptyMessage="Aucune mesure sur la fenêtre"
              emptyHint="Aucune mesure disponible pour ce périmètre sur cette période."
            >
              <LineChart
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
          <div className="mt-2.5">
            <FleetStatesChart height={170} />
          </div>
        </div>

        {/* --- Parc et alertes --- */}
        <div className="col-span-12 sm:col-span-6 xl:col-span-4 space-y-2.5">
          <Panel title="Parc supervisé" to="/equipements">
            <div className="flex items-center gap-3">
              <Donut
                size={104}
                thickness={12}
                segments={stateSegments}
                centerValue={num(states?.total, "0")}
                centerLabel="équip."
              />
              <ul className="flex-1 space-y-0.5 min-w-0">
                {stateSegments.map((segment) => (
                  <li key={segment.key} className="flex items-center gap-1.5 text-[11.5px]">
                    <span className="dot" style={{ background: segment.color }} />
                    <span className="flex-1 truncate" style={{ color: "var(--ink-2)" }}>
                      {segment.label}
                    </span>
                    <span className="num">{num(segment.value, "0")}</span>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>

          <Panel title="Alertes ouvertes">
            <div className="flex items-baseline gap-2 mb-1.5">
              <span className="num font-semibold" style={{ fontSize: 22 }}>
                {num(s?.total_open, "0")}
              </span>
              <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
                sur {num(s?.localities_affected)} sites touchés
              </span>
            </div>
            <StackedBar segments={severitySegments} height={7} />
            <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 mt-2 text-[11.5px]">
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

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 lg:col-span-7 min-w-0">
          <SlaAtRisk limit={6} />
        </div>
        <div className="col-span-12 lg:col-span-5 min-w-0">
          <Panel
            title="Heure d'apparition des alertes"
            subtitle={
              hourTotal
                ? `${pct((100 * offHours) / hourTotal, 0)} hors heures ouvrées · alertes en cours`
                : "alertes en cours"
            }
          >
            <QueryBoundary
              query={hours24}
              compact
              empty={() => hourTotal === 0}
              emptyMessage="Aucune alerte en cours"
            >
              {() => <HourHeatmap data={hourRows} />}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Collecte ETL ---
            (Plus de « charge par intervenant » : les affectations sont
            tenues dans iTop, pas dans le NOC.) */}
        <div className="col-span-12 lg:col-span-7 min-w-0">
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
                      <span className="num text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                        {tool.nodes_supervised ? `${tool.nodes_supervised} éq.` : ""}
                      </span>
                      <ToolStateBadge state={tool.state} />
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Panel>
        </div>

        {/* --- Maintenances en cours --- */}
        <div className="col-span-12 lg:col-span-5 min-w-0">
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
                      <div className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
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

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Équipements critiques --- */}
        <div className="col-span-12 lg:col-span-5 min-w-0">
          <Panel
            title="Équipements hors service"
            accent="var(--state-down)"
            to="/equipements?state=down"
            flush
          >
            <QueryBoundary
              query={criticalNodes}
              compact
              empty={(d) => !d?.items?.length}
              emptyMessage="Aucun équipement hors service"
            >
              {(data) => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {data.items.map((node) => (
                    <li key={node.node_id}>
                      <Link
                        to={`/equipements/${encodeURIComponent(node.node_id)}`}
                        className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-2)]"
                        style={{ textDecoration: "none", color: "inherit" }}
                      >
                        <NodeStateBadge state={node.state} />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] truncate font-medium">
                            {node.name}
                          </span>
                          <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                            {node.locality || "site inconnu"} · {node.node_type || "type inconnu"}
                          </span>
                        </span>
                        {/* La date de mise hors service n'est pas publiée par
                            l'instantané ; le nombre d'alertes actives l'est. */}
                        <span className="num text-[11px]" style={{ color: "var(--sev-critical)" }}>
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

        {/* --- Équipements les plus alertants --- */}
        <div className="col-span-12 lg:col-span-7 min-w-0">
          <Panel
            title="Équipements les plus alertants"
            subtitle="alertes actives des outils, à l'instant"
            to="/equipements"
            flush
          >
            <QueryBoundary
              query={topNodes}
              compact
              empty={(rows) => !rows?.some((row) => row.alerts)}
              emptyMessage="Aucun équipement en alerte"
            >
              {(rows) => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {rows
                    .filter((row) => row.alerts)
                    .map((node) => (
                      <li key={node.node_id}>
                        <Link
                          to={`/equipements/${encodeURIComponent(node.node_id)}`}
                          className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-2)]"
                          style={{ textDecoration: "none", color: "inherit" }}
                        >
                          <NodeStateBadge state={node.state} />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[12px] truncate font-medium">{node.name}</span>
                            <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                              {node.locality || "site inconnu"}
                            </span>
                          </span>
                          {node.worst_severity && <SeverityBadge severity={node.worst_severity} short />}
                          <span className="num text-[11px]" style={{ minWidth: 58, textAlign: "right" }}>
                            {node.alerts} alerte{node.alerts > 1 ? "s" : ""}
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

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Sites les plus touchés --- */}
        <div className="col-span-12 min-w-0">
          <Panel
            title="Sites les plus touchés sur 30 j"
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
      </div>

      {/* --- File courte, pour agir sans changer d'écran --- */}
      <Panel
        title="Alertes en cours"
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
              incidents={items.slice(0, 12)}
              selectedId={selectedId}
              onSelect={(row) => setSelectedId(row.id)}
            />
          )}
        </QueryBoundary>
      </Panel>

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
    <div>
      <div className="num font-semibold text-[15px]" style={{ color }}>
        {value}
      </div>
      <div className="text-[10px] uppercase tracking-[0.06em]" style={{ color: "var(--ink-3)" }}>
        {label}
      </div>
    </div>
  );
}

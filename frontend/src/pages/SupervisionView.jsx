import { useState } from "react";
import { Link } from "react-router-dom";
import { PlusCircle } from "lucide-react";

import IncidentDrawer from "../components/domain/IncidentDrawer";
import IncidentTable from "../components/domain/IncidentTable";
import ManualIncidentModal from "../components/domain/ManualIncidentModal";
import NetworkVitals from "../components/domain/NetworkVitals";
import Panel from "../components/ui/Panel";
import { StackedBar } from "../components/ui/Stat";
import { Donut, LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { Segmented } from "../components/ui/Controls";
import { NodeStateBadge, ToolStateBadge } from "../components/ui/Badge";
import { duration, num, pct, time } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { availabilityColor, toolLabel } from "../lib/vocabulary";
import {
  useAlertSummary,
  useAlerts,
  useInterop,
  useKpiLocalities,
  useMaintenanceWindows,
  useNetworkKpi,
  useNetworkSeries,
  useNodeCoverage,
  useNodeStates,
  useNodes,
  useOpenAlerts,
  useWorkload,
} from "../hooks/queries";
import { usePermission } from "../hooks/useSession";

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
  if (tool.never_collected) return "unknown";
  if (!tool.reachable) return "error";
  return tool.stale ? "stale" : "ok";
}

export default function SupervisionView() {
  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState("availability_pct");
  const [selectedId, setSelectedId] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);

  const canCreateManual = usePermission(PERMISSIONS.CREATE_MANUAL_INCIDENT);

  const summary = useAlertSummary();
  const nodeStates = useNodeStates();
  const network = useNetworkKpi({ hours });
  const series = useNetworkSeries({ metricType: metric, hours });
  const alertsQuery = useOpenAlerts({ limit: 40 });
  const workload = useWorkload();
  // Même clé de cache que useWorkload : une seule requête sert les deux.
  const allAlerts = useAlerts({ limit: 1000 });
  const interop = useInterop();
  const coverage = useNodeCoverage();
  const maintenance = useMaintenanceWindows("active");
  const localities = useKpiLocalities({ limit: 8 });
  const criticalNodes = useNodes({ state: "down", limit: 8, sort: "state" });

  const s = summary.data;
  const states = nodeStates.data;

  // « Non affectés » et « > 24 h » ne sont plus calculés par le serveur :
  // ils se lisent sur la liste des alertes, déjà chargée pour la charge
  // par intervenant.
  const openAlerts = (allAlerts.data?.alerts ?? []).filter((alert) => !alert.resolved_at);
  const unassigned = openAlerts.filter((alert) => !alert.assigned_to).length;
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
    { key: "down", label: "Hors service", value: states?.down ?? 0, color: "var(--state-down)" },
    { key: "degraded", label: "Dégradés", value: states?.degraded ?? 0, color: "var(--state-degraded)" },
    { key: "silent", label: "Muets", value: states?.silent ?? 0, color: "var(--state-silent)" },
    { key: "maintenance", label: "Maintenance", value: states?.maintenance ?? 0, color: "var(--state-maintenance)" },
    { key: "up", label: "Nominaux", value: states?.up ?? 0, color: "var(--state-up)" },
  ];

  const seriesData = series.data ?? [];
  const metricLabels = seriesData.map((point) => time(point.time));

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Salle de supervision"
        subtitle="État du réseau, charge de l'équipe et santé de la collecte"
        actions={
          <>
            <Segmented
              ariaLabel="Fenêtre d'observation"
              value={hours}
              onChange={setHours}
              options={WINDOWS}
            />
            {canCreateManual && (
              <button type="button" className="btn btn-sm" onClick={() => setManualOpen(true)}>
                <PlusCircle size={13} /> Signaler
              </button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        <NetworkVitals data={network.data} expectedNodes={states?.total} compact />
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        {/* --- Courbe réseau --- */}
        <div className="col-span-12 xl:col-span-8 min-w-0">
          <Panel
            title="Tendance réseau"
            subtitle={`moyenne sur ${seriesData.at(-1)?.nb_nodes ?? 0} équipements`}
            to="/performance"
            toLabel="Analyser"
            actions={
              <Segmented
                ariaLabel="Métrique affichée"
                value={metric}
                onChange={setMetric}
                options={[
                  { value: "availability_pct", label: "Dispo." },
                  { value: "latency_ms", label: "Latence" },
                  { value: "packet_loss_pct", label: "Pertes" },
                  { value: "bandwidth_in_mbps", label: "Trafic" },
                ]}
              />
            }
          >
            <QueryBoundary
              query={series}
              compact
              emptyMessage="Aucune mesure sur la fenêtre"
              emptyHint="Cette métrique n'est pas publiée par les connecteurs actifs, ou la collecte est arrêtée."
            >
              <LineChart
                labels={metricLabels}
                height={196}
                yMax={metric === "availability_pct" ? 100 : undefined}
                targetLine={
                  metric === "availability_pct" ? 99 : metric === "latency_ms" ? 100 : undefined
                }
                series={[
                  {
                    label:
                      metric === "availability_pct"
                        ? "Disponibilité"
                        : metric === "latency_ms"
                          ? "Latence"
                          : metric === "packet_loss_pct"
                            ? "Perte de paquets"
                            : "Trafic entrant",
                    data: seriesData.map((point) => point.value),
                    color:
                      metric === "availability_pct"
                        ? "var(--state-up)"
                        : metric === "latency_ms"
                          ? "var(--sev-info)"
                          : metric === "packet_loss_pct"
                            ? "var(--sev-high)"
                            : "var(--accent)",
                    fill: true,
                  },
                  // La bande max n'est pas un ornement : sur un agrégat de
                  // parc, la moyenne peut rester bonne alors qu'un site
                  // est à zéro. L'écart entre les deux courbes est le
                  // signal utile.
                  {
                    label: "Pire équipement",
                    data: seriesData.map((point) =>
                      metric === "availability_pct" ? point.min : point.max,
                    ),
                    color: "var(--sev-critical)",
                    dashed: true,
                    width: 1,
                  },
                ]}
              />
            </QueryBoundary>
          </Panel>
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
                sur {num(s?.localities_affected, "0")} sites touchés
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
              className="grid grid-cols-3 gap-2 mt-2.5 pt-2 border-t"
              style={{ borderColor: "var(--border)" }}
            >
              <MiniStat
                label="Non acquittés"
                value={num(s?.unacknowledged, "0")}
                color={s?.unacknowledged ? "var(--sev-medium)" : "var(--state-up)"}
              />
              <MiniStat
                label="Non affectés"
                value={num(unassigned, "0")}
                color={unassigned ? "var(--sev-high)" : "var(--state-up)"}
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
        {/* --- Charge par intervenant --- */}
        <div className="col-span-12 lg:col-span-5 min-w-0">
          <Panel
            title="Charge par intervenant"
            subtitle="incidents ouverts"
            accent="var(--accent)"
            flush
          >
            <QueryBoundary
              query={workload}
              compact
              emptyMessage="Aucun incident ouvert à répartir"
            >
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Intervenant</th>
                      <th style={{ textAlign: "right" }}>Ouverts</th>
                      <th style={{ textAlign: "right" }}>Crit.</th>
                      <th style={{ textAlign: "right" }}>Non acq.</th>
                      <th style={{ textAlign: "right" }}>Plus ancien</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((row) => {
                      const unassigned = row.user_id === null;
                      return (
                        <tr key={row.user_id ?? "unassigned"}>
                          <td>
                            <span
                              style={{
                                color: unassigned ? "var(--sev-high)" : "var(--ink)",
                                fontWeight: unassigned ? 600 : 400,
                              }}
                            >
                              {row.full_name}
                            </span>
                            {row.role && (
                              <span className="text-[10.5px] ml-1.5" style={{ color: "var(--ink-3)" }}>
                                {row.role}
                              </span>
                            )}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {num(row.open_incidents)}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: row.critical ? "var(--sev-critical)" : "var(--ink-3)",
                            }}
                          >
                            {num(row.critical, "0")}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: row.unacknowledged ? "var(--sev-medium)" : "var(--ink-3)",
                            }}
                          >
                            {num(row.unacknowledged, "0")}
                          </td>
                          <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                            {duration(row.oldest_age_minutes)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </Panel>
        </div>

        {/* --- Collecte ETL --- */}
        <div className="col-span-12 sm:col-span-6 lg:col-span-4 min-w-0">
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
        <div className="col-span-12 sm:col-span-6 lg:col-span-3 min-w-0">
          <Panel
            title="Maintenances en cours"
            accent="var(--state-maintenance)"
            to="/maintenances"
            flush
          >
            <QueryBoundary
              query={maintenance}
              compact
              emptyMessage="Aucune maintenance active"
              emptyHint="Les alertes ne sont neutralisées nulle part en ce moment."
            >
              {(windows) => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {windows.slice(0, 6).map((window) => (
                    <li key={window.id} className="px-2.5 py-1.5">
                      <div className="text-[12px] truncate">{window.reason}</div>
                      <div className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                        {window.node_name || window.node_key || window.site || "périmètre global"} · jusqu'à{" "}
                        <span className="num">{time(window.ends_at)}</span>
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

        {/* --- Sites les plus touchés --- */}
        <div className="col-span-12 lg:col-span-7 min-w-0">
          <Panel title="Sites les plus touchés ce mois" to="/carte" toLabel="Carte" flush>
            <QueryBoundary query={localities} compact emptyMessage="Aucun incident ce mois">
              {(items) => (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Site</th>
                      <th>Région</th>
                      <th style={{ textAlign: "right" }}>Incidents</th>
                      <th style={{ textAlign: "right" }}>Critiques</th>
                      <th style={{ textAlign: "right" }}>MTTR</th>
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
      </div>

      {/* --- File courte, pour agir sans changer d'écran --- */}
      <Panel
        title="Alertes en cours"
        accent="var(--sev-high)"
        to="/incidents"
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

      <IncidentDrawer
        incidentId={selectedId}
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
      />
      <ManualIncidentModal open={manualOpen} onClose={() => setManualOpen(false)} />
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

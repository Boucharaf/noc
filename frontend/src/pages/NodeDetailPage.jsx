import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, PlusCircle } from "lucide-react";

import IncidentDrawer from "../components/domain/IncidentDrawer";
import ManualIncidentModal from "../components/domain/ManualIncidentModal";
import Panel from "../components/ui/Panel";
import Stat, { DefRow, Meter } from "../components/ui/Stat";
import { LineChart } from "../components/charts";
import { NodeStateBadge, SeverityBadge, StatusBadge, ToolTag } from "../components/ui/Badge";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { Segmented } from "../components/ui/Controls";
import { ageFrom, bandwidth, dateTime, decimal, duration, num, pct, smartTime } from "../lib/format";
import { METRIC_TYPES, metricMeta, nodeStateMeta, thresholdColor, toolLabel } from "../lib/vocabulary";
import { PERMISSIONS } from "../lib/permissions";
import {
  useNode,
  useNodeIncidents,
  useNodeLatest,
  useNodeSeries,
} from "../hooks/queries";
import { usePermission } from "../hooks/useSession";

/**
 * Fiche d'équipement — NIVEAU 4 du document métier
 * (« Équipement | Interface | CPU | RAM | trafic | latence | pertes |
 *   historique »).
 *
 * C'est l'écran d'arrivée de tous les drill-downs : un clic sur un nom
 * d'équipement, où qu'il apparaisse dans l'application, mène ici.
 *
 * Les onglets de métrique n'affichent QUE les séries réellement
 * collectées pour cet équipement (`metric_types`, renvoyé par le
 * backend). Proposer sept onglets dont cinq sont vides laisse croire à
 * une panne de l'interface, alors que le vrai message est « Centreon ne
 * publie pas la mémoire pour ce type de sonde ».
 */

const WINDOWS = [
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 72, label: "3 j" },
  { value: 168, label: "7 j" },
  { value: 720, label: "30 j" },
];

export default function NodeDetailPage() {
  const { nodeId } = useParams();
  const navigate = useNavigate();
  const id = Number(nodeId);

  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState(null);
  const [selectedIncident, setSelectedIncident] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);

  const nodeQuery = useNode(id);
  const latest = useNodeLatest(id);
  const incidents = useNodeIncidents(id, 30);

  const node = nodeQuery.data;
  const availableMetrics = node?.metric_types?.length ? node.metric_types : [];
  const activeMetric = metric ?? availableMetrics[0] ?? null;
  const series = useNodeSeries(id, activeMetric, hours);

  const meta = activeMetric ? metricMeta(activeMetric) : null;
  const stateMeta = node ? nodeStateMeta(node.state) : null;
  const canCreateManual = usePermission(PERMISSIONS.CREATE_MANUAL_INCIDENT);

  return (
    <div className="space-y-2.5">
      <PageHeader
        title={node?.name ?? "Équipement"}
        subtitle={
          node
            ? [node.locality, node.region, node.ministry].filter(Boolean).join(" · ") ||
              "Aucun rattachement géographique connu"
            : undefined
        }
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => navigate(-1)}>
              <ArrowLeft size={13} /> Retour
            </button>
            {canCreateManual && (
              <button type="button" className="btn btn-sm" onClick={() => setManualOpen(true)}>
                <PlusCircle size={13} /> Signaler une panne
              </button>
            )}
          </>
        }
      >
        {node && (
          <div className="flex items-center gap-2 ml-3">
            <NodeStateBadge state={node.state} />
            {node.maintenance_until && (
              <span className="text-[11px]" style={{ color: "var(--state-maintenance)" }}>
                maintenance jusqu'à {smartTime(node.maintenance_until)}
              </span>
            )}
          </div>
        )}
      </PageHeader>

      <QueryBoundary query={nodeQuery} empty={(d) => !d}>
        {(data) => (
          <>
            {/* --- Dernières mesures --- */}
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
              {METRIC_TYPES.map((type) => {
                const info = metricMeta(type);
                const point = latest.data?.[type];
                const value = point?.value ?? null;
                return (
                  <Stat
                    key={type}
                    compact
                    label={info.label}
                    value={
                      value === null
                        ? "—"
                        : type.startsWith("bandwidth")
                          ? bandwidth(value)
                          : `${decimal(value, info.digits)}${info.unit === "%" ? " %" : info.unit ? ` ${info.unit}` : ""}`
                    }
                    color={value === null ? "var(--ink-3)" : thresholdColor(type, value) ?? undefined}
                    hint={point ? ageFrom(point.time) : "non collectée"}
                  />
                );
              })}
            </div>

            <div className="grid grid-cols-12 gap-2.5">
              {/* --- Séries temporelles --- */}
              <div className="col-span-12 xl:col-span-8 min-w-0">
                <Panel
                  title="Télémétrie"
                  subtitle={
                    activeMetric
                      ? `${meta.label}${meta.unit ? ` (${meta.unit})` : ""}`
                      : undefined
                  }
                  actions={
                    <Segmented
                      ariaLabel="Fenêtre"
                      value={hours}
                      onChange={setHours}
                      options={WINDOWS}
                    />
                  }
                >
                  {availableMetrics.length === 0 ? (
                    <p className="text-[12px] py-6 text-center" style={{ color: "var(--ink-3)" }}>
                      Aucune métrique reçue pour cet équipement sur les 7 derniers jours.
                      <br />
                      <span className="text-[11px]">
                        Les outils qui le supervisent ({data.source_tools.map(toolLabel).join(", ") || "aucun"})
                        ne publient pas de mesure, ou la collecte est arrêtée.
                      </span>
                    </p>
                  ) : (
                    <>
                      <div className="flex flex-wrap gap-1 mb-2">
                        {availableMetrics.map((type) => {
                          const info = metricMeta(type);
                          const active = type === activeMetric;
                          return (
                            <button
                              key={type}
                              type="button"
                              className="btn btn-sm"
                              style={{
                                background: active ? "var(--accent-soft)" : undefined,
                                borderColor: active ? "var(--accent)" : undefined,
                                color: active ? "var(--accent-ink)" : undefined,
                              }}
                              onClick={() => setMetric(type)}
                            >
                              {info.label}
                            </button>
                          );
                        })}
                      </div>
                      <QueryBoundary
                        query={series}
                        compact
                        emptyMessage="Aucun point sur cette fenêtre"
                      >
                        {(points) => (
                          <>
                            <LineChart
                              height={230}
                              labels={points.map((point) => smartTime(point.time))}
                              yMax={meta.unit === "%" ? 100 : undefined}
                              targetLine={meta.target}
                              valueFormatter={(value) =>
                                `${decimal(value, meta.digits)} ${meta.unit}`
                              }
                              series={[
                                {
                                  label: meta.label,
                                  data: points.map((point) => point.value),
                                  color: meta.color,
                                  fill: true,
                                },
                              ]}
                            />
                            <div
                              className="flex gap-5 mt-2 pt-2 border-t text-[11.5px]"
                              style={{ borderColor: "var(--border)" }}
                            >
                              <SeriesStat label="Minimum" points={points} pick={Math.min} meta={meta} metricType={activeMetric} />
                              <SeriesStat label="Moyenne" points={points} pick={null} meta={meta} metricType={activeMetric} />
                              <SeriesStat label="Maximum" points={points} pick={Math.max} meta={meta} metricType={activeMetric} />
                              <span style={{ color: "var(--ink-3)" }} className="ml-auto">
                                <span className="num">{points.length}</span> points ·{" "}
                                {hours <= 48 ? "données brutes" : "agrégat horaire"}
                              </span>
                            </div>
                          </>
                        )}
                      </QueryBoundary>
                    </>
                  )}
                </Panel>
              </div>

              {/* --- Identité --- */}
              <div className="col-span-12 xl:col-span-4 space-y-2.5">
                <Panel title="Identité">
                  <DefRow label="Nom">{data.name}</DefRow>
                  <DefRow label="Adresse IP" mono>
                    {data.ip_address || "—"}
                  </DefRow>
                  <DefRow label="Type">{data.node_type || "non renseigné"}</DefRow>
                  <DefRow label="État">
                    <span style={{ color: stateMeta.color }}>{stateMeta.label}</span>
                    <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                      {stateMeta.hint}
                    </span>
                  </DefRow>
                  <DefRow label="Site">
                    {data.locality_id ? (
                      <Link
                        to={`/equipements?locality_id=${data.locality_id}`}
                        style={{ color: "var(--accent-ink)" }}
                      >
                        {data.locality}
                      </Link>
                    ) : (
                      "non rattaché"
                    )}
                  </DefRow>
                  <DefRow label="Région">{data.region || "—"}</DefRow>
                  <DefRow label="Ministère">{data.ministry || "—"}</DefRow>
                  <DefRow label="Dernière mesure" mono>
                    {data.last_metric_at ? dateTime(data.last_metric_at) : "jamais"}
                  </DefRow>
                  {data.down_since && (
                    <DefRow label="Hors service depuis" mono>
                      <span style={{ color: "var(--sev-critical)" }}>
                        {dateTime(data.down_since)} ({ageFrom(data.down_since)})
                      </span>
                    </DefRow>
                  )}
                </Panel>

                <Panel title="Supervision" subtitle="identifiants par outil">
                  {data.source_refs?.length ? (
                    <ul className="space-y-1">
                      {data.source_refs.map((ref) => (
                        <li
                          key={`${ref.source_tool}-${ref.external_ref}`}
                          className="flex items-center gap-2 text-[12px]"
                        >
                          <span className="font-medium" style={{ minWidth: 84 }}>
                            {toolLabel(ref.source_tool)}
                          </span>
                          <span className="mono-xs truncate" style={{ color: "var(--ink-3)" }}>
                            {ref.external_ref}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-[11.5px]" style={{ color: "var(--sev-medium)" }}>
                      Aucun outil ne déclare cet équipement. Il est présent dans
                      l'inventaire mais n'est supervisé par personne.
                    </p>
                  )}
                </Panel>

                <Panel title="Historique">
                  <div className="grid grid-cols-2 gap-2">
                    <Stat compact label="Incidents 30 j" value={num(data.incidents_30d, "0")} />
                    <Stat compact label="Incidents 90 j" value={num(data.incidents_90d, "0")} />
                    <Stat
                      compact
                      label="MTTR moyen 90 j"
                      value={duration(data.avg_mttr_minutes)}
                      color={
                        data.avg_mttr_minutes > 240 ? "var(--sev-high)" : "var(--state-up)"
                      }
                    />
                    <Stat
                      compact
                      label="Indispo. 30 j"
                      value={duration(data.downtime_30d_minutes)}
                    />
                  </div>
                  {data.availability_pct !== null && data.availability_pct !== undefined && (
                    <div className="mt-2">
                      <div className="flex justify-between text-[11px] mb-1">
                        <span style={{ color: "var(--ink-3)" }}>Disponibilité courante</span>
                        <span className="num">{pct(data.availability_pct, 2)}</span>
                      </div>
                      <Meter
                        value={data.availability_pct}
                        color={thresholdColor("availability_pct", data.availability_pct)}
                      />
                    </div>
                  )}
                </Panel>
              </div>
            </div>

            {/* --- Incidents de cet équipement --- */}
            <Panel
              title="Incidents de cet équipement"
              subtitle="30 derniers"
              flush
              to={`/incidents?q=${encodeURIComponent(data.name)}`}
              toLabel="Tout l'historique"
            >
              <QueryBoundary
                query={incidents}
                compact
                emptyMessage="Aucun incident enregistré"
                emptyHint="Cet équipement n'a jamais déclenché d'alerte dans les outils de supervision."
              >
                {(items) => (
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th style={{ width: 82 }}>Gravité</th>
                        <th style={{ width: 92 }}>Statut</th>
                        <th style={{ width: 110 }}>Détecté</th>
                        <th style={{ width: 150 }}>Cause</th>
                        <th>Description</th>
                        <th style={{ width: 80, textAlign: "right" }}>MTTR</th>
                        <th style={{ width: 84 }}>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((incident) => (
                        <tr
                          key={incident.id}
                          className={`row-clickable sev-edge sev-edge-${incident.severity}`}
                          onClick={() => setSelectedIncident(incident.id)}
                        >
                          <td>
                            <SeverityBadge severity={incident.severity} />
                          </td>
                          <td>
                            <StatusBadge status={incident.status} />
                          </td>
                          <td className="num" style={{ color: "var(--ink-3)" }}>
                            {smartTime(incident.detected_at)}
                          </td>
                          <td style={{ color: "var(--ink-2)" }}>
                            {incident.cause_label || incident.cause_category || "—"}
                          </td>
                          <td className="truncate-cell" title={incident.description ?? ""}>
                            {incident.description || "—"}
                          </td>
                          <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                            {duration(incident.mttr_minutes)}
                          </td>
                          <td>
                            <ToolTag tool={incident.source_tool} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </QueryBoundary>
            </Panel>
          </>
        )}
      </QueryBoundary>

      <IncidentDrawer
        incidentId={selectedIncident}
        open={Boolean(selectedIncident)}
        onClose={() => setSelectedIncident(null)}
      />
      <ManualIncidentModal
        open={manualOpen}
        onClose={() => setManualOpen(false)}
        defaultNodeCode={node?.name ?? ""}
      />
    </div>
  );
}

/** Min / moyenne / max d'une série — le résumé qu'un graphe seul ne donne pas. */
function SeriesStat({ label, points, pick, meta, metricType }) {
  const values = points.map((point) => point.value).filter((value) => value !== null);
  if (values.length === 0) return null;
  const value = pick
    ? pick(...values)
    : values.reduce((sum, current) => sum + current, 0) / values.length;
  return (
    <span>
      <span style={{ color: "var(--ink-3)" }}>{label} </span>
      <span className="num" style={{ color: thresholdColor(metricType, value) ?? "var(--ink)" }}>
        {decimal(value, meta.digits)} {meta.unit}
      </span>
    </span>
  );
}

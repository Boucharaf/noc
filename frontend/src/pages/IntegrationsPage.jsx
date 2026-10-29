import { useState } from "react";
import { Link } from "react-router-dom";

import Panel from "../components/ui/Panel";
import Stat, { Meter } from "../components/ui/Stat";
import { Donut, LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { Pagination } from "../components/ui/Table";
import { ToolStateBadge } from "../components/ui/Badge";
import { ageFrom, dateTime, num, pct } from "../lib/format";
import { toolLabel } from "../lib/vocabulary";
import {
  useCoverage,
  useCoverageTrend,
  useHealth,
  useInterop,
  useMergeReport,
  useNodeStates,
} from "../hooks/queries";

/**
 * Santé de la chaîne de collecte.
 *
 * Écran le moins spectaculaire et le plus important de l'application :
 * tous les autres affichent des données que CELUI-CI garantit. Un
 * connecteur arrêté ne fait baisser aucun compteur — il fige simplement
 * les chiffres, et un NOC qui regarde un tableau figé croit que tout va
 * bien.
 *
 * D'où la mise en avant de la DATE DE DERNIÈRE COLLECTE par outil, plus
 * que du nombre d'objets remontés : « 4 210 équipements » est rassurant
 * même quand la valeur date de trois jours.
 */
export default function IntegrationsPage() {
  const [coveragePage, setCoveragePage] = useState(1);
  const interop = useInterop();
  const coverage = useCoverage();
  const trend = useCoverageTrend(60);
  const health = useHealth();
  const nodeStates = useNodeStates();
  const merge = useMergeReport();

  const trendPoints = trend.data ?? [];
  const toolsHealthy = (interop.data?.tools ?? []).filter(
    (tool) => tool.reachable && !tool.stale,
  ).length;
  const toolsTotal = interop.data?.tools?.length ?? 0;
  const staleStreams = Object.entries(interop.data?.source_data ?? {}).flatMap(
    ([tool, streams]) =>
      Object.entries(streams)
        .filter(([, stream]) => stream.stale || stream.available === false)
        .map(([collection, stream]) => ({
          tool,
          collection,
          collectedAt: stream.collected_at,
          available: stream.available,
        })),
  );

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Collecte et interopérabilité"
        subtitle="État des outils de supervision et couverture du parc"
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <Stat
          label="Outils actifs"
          value={
            interop.data
              ? `${toolsHealthy}/${toolsTotal}`
              : "—"
          }
          color={
            toolsTotal > 0 && toolsHealthy === 0
              ? "var(--sev-critical)"
              : toolsHealthy < toolsTotal
                ? "var(--sev-medium)"
                : "var(--state-up)"
          }
        />
        <Stat
          label="Intervalle de collecte"
          value={
            interop.data?.collector?.interval_s
              ? `${Math.round(interop.data.collector.interval_s / 60)} min`
              : "—"
          }
        />
        <Stat
          label="Plateforme"
          value={
            !health.data
              ? "—"
              : health.data.status === "ok"
                ? "opérationnelle"
                : "perturbée"
          }
          color={health.data?.status === "ok" ? "var(--state-up)" : "var(--sev-critical)"}
        />
        <Stat
          label="Équipements connus"
          value={num(nodeStates.data?.total, "—")}
          to="/equipements"
        />
        <Stat
          label="État inconnu"
          value={num((nodeStates.data?.unknown ?? 0) + (nodeStates.data?.silent ?? 0))}
          color={nodeStates.data?.unknown ? "var(--sev-medium)" : "var(--state-up)"}
          to="/equipements?state=unknown"
          hint="aucune mesure depuis 6 h"
        />
      </div>

      <Panel title="Outils de supervision" flush>
        <QueryBoundary
          query={interop}
          empty={(data) => !data?.tools?.length}
          emptyMessage="Aucun outil configuré"
        >
          {(data) => (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 140 }}>Outil</th>
                  <th style={{ width: 130 }}>État</th>
                  <th style={{ width: 150 }}>Dernière collecte</th>
                  <th style={{ textAlign: "right", width: 90 }}>Équipements</th>
                  <th style={{ textAlign: "right", width: 105 }}>Alertes techniques</th>
                  <th style={{ textAlign: "right", width: 90 }}>Tickets ITSM</th>
                  <th style={{ textAlign: "right", width: 90 }}>Métriques</th>
                  <th style={{ textAlign: "right", width: 110 }}>Inc. ce mois</th>
                  <th className="wrap">Détail</th>
                </tr>
              </thead>
              <tbody>
                {data.tools.map((tool) => (
                  <tr key={tool.tool}>
                    <td className="font-medium">{toolLabel(tool.tool)}</td>
                    <td>
                      <ToolStateBadge state={tool.state} />
                    </td>
                    <td className="num" title={dateTime(tool.last_run_at)}>
                      {tool.last_run_at ? (
                        <span
                          style={{
                            color:
                              tool.state === "ok" ? "var(--ink-2)" : "var(--sev-medium)",
                          }}
                        >
                          il y a {ageFrom(tool.last_run_at)}
                        </span>
                      ) : (
                        <span style={{ color: "var(--ink-3)" }}>jamais</span>
                      )}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {num(tool.nb_nodes, "—")}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {num(tool.nb_technical_alerts, "—")}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {num(tool.nb_itsm_tickets, "—")}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {num(tool.nb_metrics, "—")}
                    </td>
                    <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                      {num(tool.incidents_this_month, "0")}
                    </td>
                    <td className="wrap" style={{ color: "var(--ink-3)", fontSize: 11.5 }}>
                      {tool.detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Panel>

      <Panel
        title="Qualité du rapprochement"
        subtitle="Les cas ambigus restent séparés ; les états contradictoires ne sont pas masqués."
      >
        <QueryBoundary query={merge} compact>
          {(data) => (
            <div className="space-y-2 text-[11.5px]">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <Row label="Équipements fusionnés" value={num(data.duplicates_resolved, "0")} />
                <Row label="Identités confirmées" value={num(data.matched_by_verified_identity, "0")} />
                <Row label="Correspondances ambiguës" value={num(data.ambiguous_total, "0")} />
                <Row label="Conflits d'état" value={num(data.state_conflicts?.length, "0")} />
              </div>
              {!!data.ambiguities?.length && (
                <ul className="space-y-1 border-t pt-2" style={{ borderColor: "var(--border)" }}>
                  {data.ambiguities.slice(0, 5).map((item, index) => (
                    <li key={`${item.reason}-${item.identity}-${index}`} className="flex gap-2">
                      <span style={{ color: "var(--sev-medium)" }}>{item.reason}</span>
                      <span className="truncate" title={item.identity}>{item.identity}</span>
                      <span style={{ color: "var(--ink-3)" }}>{item.sources}</span>
                    </li>
                  ))}
                </ul>
              )}
              {!!data.state_conflicts?.length && (
                <p style={{ color: "var(--sev-medium)" }}>
                  États non consolidés : {data.state_conflicts.slice(0, 5).map((item) => item.id).join(", ")}
                </p>
              )}
              {!!staleStreams.length && (
                <ul
                  className="space-y-1 border-t pt-2"
                  style={{ borderColor: "var(--border)", color: "var(--sev-medium)" }}
                >
                  {staleStreams.map((stream) => (
                    <li key={`${stream.tool}-${stream.collection}`}>
                      {toolLabel(stream.tool)} — {stream.collection}: dernier succès{" "}
                      {stream.collectedAt ? dateTime(stream.collectedAt) : "inconnu"}
                      {!stream.available && " (aucune donnée antérieure)"}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </QueryBoundary>
      </Panel>

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 lg:col-span-6">
          <Panel
            title="Vus par un seul outil"
            subtitle="si cet outil tombe, l'équipement sort de la vue sans que rien ne le signale"
            flush
          >
            <QueryBoundary
              query={merge}
              compact
              empty={(d) => !d?.single_source_nodes?.length}
              emptyMessage="Chaque équipement est vu par au moins deux outils"
            >
              {(data) => (
                <>
                  <p className="px-3 pt-2 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                    {num(data.single_source_total ?? data.single_source_nodes.length)} équipement(s)
                    {data.single_source_total > data.single_source_nodes.length &&
                      ` — les ${data.single_source_nodes.length} premiers`}
                  </p>
                  <ul className="max-h-64 overflow-auto px-3 py-2 space-y-1 text-[12px]">
                    {data.single_source_nodes.map((item) => (
                      <li key={item.id ?? item.name} className="flex items-center gap-2">
                        {item.id ? (
                          <Link to={`/equipements/${encodeURIComponent(item.id)}`} className="truncate hover:underline">
                            {item.name}
                          </Link>
                        ) : (
                          <span className="truncate">{item.name}</span>
                        )}
                        {item.tool && (
                          <span className="ml-auto shrink-0 text-[11px]" style={{ color: "var(--ink-3)" }}>
                            {toolLabel(item.tool)} seul
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </QueryBoundary>
          </Panel>
        </div>
        <div className="col-span-12 lg:col-span-6">
          <Panel
            title="Alertes sans équipement"
            subtitle="la source cite un équipement absent de l'inventaire collecté"
            flush
          >
            <QueryBoundary
              query={merge}
              compact
              empty={(d) => !d?.orphan_alerts}
              emptyMessage="Toutes les alertes sont rattachées à un équipement"
            >
              {(data) => (
                <>
                  <p className="px-3 pt-2 text-[11.5px]" style={{ color: "var(--sev-medium)" }}>
                    {num(data.orphan_alerts)} alerte(s) ou ticket(s) non rattaché(s)
                    {data.orphan_samples?.length < data.orphan_alerts &&
                      ` — les ${data.orphan_samples.length} premiers`}
                  </p>
                  <ul className="max-h-64 overflow-auto px-3 py-2 space-y-1.5 text-[12px]">
                    {(data.orphan_samples ?? []).map((alert) => (
                      <li key={alert.key}>
                        <span className="font-medium">{toolLabel(alert.tool)}</span>
                        {alert.kind === "itsm_ticket" && " (ticket)"} — {alert.message}
                        <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                          équipement cité : {alert.node_name || alert.node_ref || "aucun"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 lg:col-span-4">
          <Panel title="Couverture de supervision">
            <QueryBoundary query={coverage} compact empty={(d) => !d}>
              {(data) => (
                <>
                  <div className="flex items-center gap-3">
                    <Donut
                      size={110}
                      thickness={12}
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
                      <Row label="Parc total" value={num(data.total_assets)} />
                      <Row
                        label="Supervisés"
                        value={num(data.monitored_assets)}
                        color="var(--state-up)"
                      />
                      <Row
                        label="Non supervisés"
                        value={num(data.unmonitored_assets)}
                        color="var(--sev-high)"
                      />
                      <Row label="Arrêté au" value={data.as_of} />
                      <Row label="Source" value={data.source} />
                    </div>
                  </div>
                  {!data.is_complete_inventory && (
                    <p
                      className="text-[11px] mt-2 pt-2 border-t"
                      style={{ borderColor: "var(--border)", color: "var(--sev-medium)" }}
                    >
                      Ce taux compare le parc aux équipements que les outils remontent —
                      soit aujourd'hui le même ensemble. Il ne deviendra significatif que
                      lorsqu'un inventaire théorique complet (CMDB iTop) alimentera
                      <code className="mono-xs"> dim_node</code>.
                    </p>
                  )}
                </>
              )}
            </QueryBoundary>
          </Panel>
        </div>

        <div className="col-span-12 lg:col-span-8 min-w-0">
          <Panel title="Évolution de la couverture" subtitle="60 derniers jours">
            <QueryBoundary
              query={trend}
              compact
              emptyMessage="Aucun historique de couverture"
            >
              <LineChart
                height={200}
                labels={trendPoints.map((point) => point.date)}
                legend
                series={[
                  {
                    label: "Parc total",
                    data: trendPoints.map((point) => point.total_assets),
                    color: "var(--ink-3)",
                    dashed: true,
                  },
                  {
                    label: "Supervisés",
                    data: trendPoints.map((point) => point.monitored_assets),
                    color: "var(--state-up)",
                    fill: true,
                  },
                ]}
              />
            </QueryBoundary>
          </Panel>
        </div>
      </div>

      <Panel title="Couverture par site" flush>
        <QueryBoundary query={coverage} compact empty={(d) => !d?.by_locality?.length}>
          {(data) => (
            <>
            <div style={{ maxHeight: 360, overflow: "auto" }}>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Site</th>
                    <th>Région</th>
                    <th className="wrap">Ministère</th>
                    <th style={{ textAlign: "right" }}>Total</th>
                    <th style={{ textAlign: "right" }}>Supervisés</th>
                    <th style={{ textAlign: "right" }}>Manquants</th>
                    <th style={{ width: 120 }}>Couverture</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_locality
                    .slice((coveragePage - 1) * 25, coveragePage * 25)
                    .map((row, index) => (
                    <tr key={`${row.locality_id ?? row.locality}-${index}`}>
                      <td>{row.locality}</td>
                      <td style={{ color: "var(--ink-3)" }}>{row.region}</td>
                      <td className="truncate-cell" style={{ color: "var(--ink-3)" }}>
                        {row.ministry}
                      </td>
                      <td className="num" style={{ textAlign: "right" }}>
                        {num(row.total_assets)}
                      </td>
                      <td className="num" style={{ textAlign: "right", color: "var(--state-up)" }}>
                        {num(row.monitored_assets)}
                      </td>
                      <td
                        className="num"
                        style={{
                          textAlign: "right",
                          color: row.unmonitored_assets ? "var(--sev-high)" : "var(--ink-3)",
                        }}
                      >
                        {num(row.unmonitored_assets)}
                      </td>
                      <td>
                        <div className="flex items-center gap-1.5">
                          <Meter
                            value={row.coverage_pct}
                            color={
                              (row.coverage_pct ?? 0) >= 95
                                ? "var(--state-up)"
                                : (row.coverage_pct ?? 0) >= 80
                                  ? "var(--sev-medium)"
                                  : "var(--sev-critical)"
                            }
                          />
                          <span className="num text-[11px]" style={{ width: 40, textAlign: "right" }}>
                            {pct(row.coverage_pct, 0)}
                          </span>
                        </div>
                      </td>
                    </tr>
                    ))}
                </tbody>
              </table>
            </div>
            <Pagination
              page={coveragePage}
              pages={Math.max(1, Math.ceil(data.by_locality.length / 25))}
              total={data.by_locality.length}
              pageSize={25}
              onChange={setCoveragePage}
              label="sites"
            />
            </>
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

function Row({ label, value, color }) {
  return (
    <div className="flex justify-between gap-2">
      <span style={{ color: "var(--ink-2)" }}>{label}</span>
      <span className="num truncate" style={{ color: color ?? "var(--ink)" }}>
        {value}
      </span>
    </div>
  );
}

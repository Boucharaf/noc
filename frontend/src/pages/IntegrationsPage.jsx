import Panel from "../components/ui/Panel";
import Stat, { Meter } from "../components/ui/Stat";
import { Donut, LineChart } from "../components/charts";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { ToolStateBadge } from "../components/ui/Badge";
import { ageFrom, dateTime, num, pct } from "../lib/format";
import { toolLabel } from "../lib/vocabulary";
import {
  useCoverage,
  useCoverageTrend,
  useHealth,
  useInterop,
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
  const interop = useInterop();
  const coverage = useCoverage();
  const trend = useCoverageTrend(60);
  const health = useHealth();
  const nodeStates = useNodeStates();

  const trendPoints = trend.data ?? [];

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Collecte et interopérabilité"
        subtitle="État des six connecteurs de l'ETL et couverture de supervision"
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2">
        <Stat
          label="Connecteurs actifs"
          value={
            interop.data
              ? `${interop.data.tools_healthy}/${interop.data.tools_total}`
              : "—"
          }
          color={
            interop.data?.tools_healthy === 0
              ? "var(--sev-critical)"
              : interop.data?.tools_healthy < interop.data?.tools_total
                ? "var(--sev-medium)"
                : "var(--state-up)"
          }
        />
        <Stat
          label="Intervalle de collecte"
          value={
            interop.data ? `${Math.round(interop.data.interval_seconds / 60)} min` : "—"
          }
          hint="COLLECT_INTERVAL_S"
        />
        <Stat
          label="Entrepôt"
          value={health.data?.checks?.database?.status ?? "—"}
          color={
            health.data?.checks?.database?.status === "ok"
              ? "var(--state-up)"
              : "var(--sev-critical)"
          }
          hint={health.data?.checks?.database?.detail}
        />
        <Stat
          label="Redis"
          value={health.data?.checks?.redis?.status ?? "—"}
          color={
            health.data?.checks?.redis?.status === "ok"
              ? "var(--state-up)"
              : "var(--sev-critical)"
          }
        />
        <Stat
          label="Équipements connus"
          value={num(nodeStates.data?.total, "—")}
          to="/equipements"
        />
        <Stat
          label="Équipements muets"
          value={num(nodeStates.data?.silent, "0")}
          color={nodeStates.data?.silent ? "var(--sev-medium)" : "var(--state-up)"}
          to="/equipements?state=silent"
          hint="aucune mesure depuis 6 h"
        />
      </div>

      <Panel title="Connecteurs" flush>
        <QueryBoundary
          query={interop}
          empty={(data) => !data?.tools?.length}
          emptyMessage="Aucun connecteur configuré"
        >
          {(data) => (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 140 }}>Outil</th>
                  <th style={{ width: 130 }}>État</th>
                  <th style={{ width: 150 }}>Dernière collecte</th>
                  <th style={{ textAlign: "right", width: 90 }}>Équipements</th>
                  <th style={{ textAlign: "right", width: 90 }}>Incidents</th>
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
                      {num(tool.nb_incidents, "—")}
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
              emptyHint="fact_supervision_coverage_daily est alimentée par l'ETL à chaque cycle."
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
                  {data.by_locality.map((row, index) => (
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
                        {num(row.unmonitored_assets, "0")}
                      </td>
                      <td>
                        <div className="flex items-center gap-1.5">
                          <Meter
                            value={row.coverage_pct ?? 0}
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

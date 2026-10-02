import { useState } from "react";
import { Link } from "react-router-dom";

import NetworkVitals from "../components/domain/NetworkVitals";
import Panel from "../components/ui/Panel";
import { LineChart } from "../components/charts";
import { FilterSelect, Segmented, Toolbar } from "../components/ui/Controls";
import { Meter } from "../components/ui/Stat";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { METRIC_TYPES, metricMeta, thresholdColor } from "../lib/vocabulary";
import { bandwidth, decimal, num, smartTime } from "../lib/format";
import {
  useNetworkKpi,
  useNetworkRanking,
  useNetworkSeries,
  useNodeStates,
  useNodes,
} from "../hooks/queries";

/**
 * Performance réseau — les « KPI réseau » du document métier
 * (disponibilité, pertes, latence, bande passante).
 *
 * Deux lectures complémentaires, côte à côte :
 *
 *   · la COURBE agrégée répond à « comment se comporte le réseau » ;
 *   · le CLASSEMENT répond à « qui tire la moyenne vers le bas ».
 *
 * L'une sans l'autre est trompeuse : une latence moyenne de 40 ms peut
 * recouvrir 290 sites à 15 ms et 10 sites à 800 ms. Le classement suit
 * automatiquement le sens de la métrique — pire latence en tête, plus
 * mauvaise disponibilité en tête, plus gros débit en tête.
 */

const WINDOWS = [
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 72, label: "3 j" },
  { value: 168, label: "7 j" },
  { value: 720, label: "30 j" },
];

export default function PerformancePage() {
  const [hours, setHours] = useState(24);
  const [metric, setMetric] = useState("latency_ms");
  const [site, setSite] = useState(null);
  const [organisation, setOrganisation] = useState(null);
  const [nodeType, setNodeType] = useState(null);

  const allNodesQuery = useNodes({ limit: 2000 });
  const allNodes = allNodesQuery.data?.items ?? [];
  const siteOptions = [
    ...new Set(allNodes.map((n) => n.locality).filter(Boolean)),
  ].map((s) => ({ value: s, label: s }));
  const orgOptions = [
    ...new Set(allNodes.map((n) => n.organisation).filter(Boolean)),
  ].map((o) => ({ value: o, label: o }));
  const typeOptions = [
    ...new Set(allNodes.map((n) => n.node_type).filter(Boolean)),
  ].map((t) => ({ value: t, label: t }));

  const nodeStates = useNodeStates();
  const network = useNetworkKpi();
  const series = useNetworkSeries({
    metricType: metric,
    hours,
    sample: 15,
    site,
    organisation,
    nodeType,
  });
  const top = useNetworkRanking({
    metricType: metric,
    hours,
    sample: 15,
    site,
    organisation,
    nodeType,
  });

  const meta = metricMeta(metric);
  const points = series.data ?? [];

  const formatValue = (value) =>
    metric.startsWith("bandwidth")
      ? bandwidth(value)
      : `${decimal(value, meta.digits)}${meta.unit === "%" ? " %" : ` ${meta.unit}`}`;

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Performance réseau"
        subtitle="Courbes historiques lues auprès des outils sources · disponibilité instantanée du parc"
        actions={
          <Toolbar>
            <FilterSelect
              label="Périmètre"
              value={site}
              onChange={setSite}
              allLabel="Tous les sites"
              width={170}
              options={siteOptions}
            />
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
              ariaLabel="Fenêtre"
              value={hours}
              onChange={setHours}
              options={WINDOWS}
            />
          </Toolbar>
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        <NetworkVitals
          data={network.data}
          expectedNodes={nodeStates.data?.total}
          compact
        />
      </div>

      <div className="flex flex-wrap gap-1">
        {METRIC_TYPES.map((type) => {
          const info = metricMeta(type);
          const active = type === metric;
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

      <div className="grid grid-cols-12 gap-2.5">
        <div className="col-span-12 xl:col-span-8 min-w-0">
          <Panel
            title={meta.label}
            subtitle={
              points.length
                ? `moyenne de ${points.at(-1)?.nb_nodes ?? 0}/${points.at(-1)?.sampled_nodes ?? 0} équipements mesurés, échantillon priorisé par alertes · ${
                    hours <= 48 ? "données brutes" : "agrégat horaire"
                  }`
                : undefined
            }
          >
            <QueryBoundary
              query={series}
              compact
              emptyMessage="Aucune mesure sur cette fenêtre"
              emptyHint="Zabbix, Centreon et NetXMS peuvent publier ces séries; iTop fournit la CMDB, pas les métriques."
            >
              <LineChart
                height={280}
                labels={points.map((point) => smartTime(point.time))}
                yMax={meta.unit === "%" ? 100 : undefined}
                targetLine={meta.target}
                valueFormatter={(value) =>
                  `${decimal(value, meta.digits)} ${meta.unit}`
                }
                legend
                series={[
                  {
                    label: `${meta.label} — moyenne`,
                    data: points.map((point) => point.value),
                    color: meta.color,
                    fill: true,
                  },
                  {
                    label: "Meilleur équipement",
                    data: points.map((point) => point.min),
                    color: "var(--state-up)",
                    dashed: true,
                    width: 1,
                  },
                  {
                    label: "Pire équipement",
                    data: points.map((point) => point.max),
                    color: "var(--sev-critical)",
                    dashed: true,
                    width: 1,
                  },
                ]}
              />
            </QueryBoundary>
          </Panel>
        </div>

        <div className="col-span-12 xl:col-span-4 min-w-0">
          <Panel
            title={
              meta.higherIsBetter === true
                ? `Plus faible ${meta.label.toLowerCase()}`
                : meta.higherIsBetter === false
                  ? `Plus forte ${meta.label.toLowerCase()}`
                  : `Plus gros ${meta.label.toLowerCase()}`
            }
            subtitle={`sur ${hours} h`}
            flush
          >
            <QueryBoundary
              query={top}
              compact
              emptyMessage="Aucun classement disponible"
            >
              {(items) => {
                const ranked = [...items].sort((left, right) =>
                  meta.higherIsBetter === true
                    ? left.avg_value - right.avg_value
                    : right.avg_value - left.avg_value,
                );
                const max = Math.max(
                  ...ranked.map((item) => item.avg_value),
                  1,
                );
                return (
                  <ul
                    className="divide-y"
                    style={{ borderColor: "var(--border)" }}
                  >
                    {ranked.map((item, index) => (
                      <li key={item.node_id} className="px-2.5 py-1.5">
                        <div className="flex items-baseline gap-2">
                          <span
                            className="num text-[10.5px]"
                            style={{ color: "var(--ink-3)", width: 16 }}
                          >
                            {index + 1}
                          </span>
                          <Link
                            to={`/equipements/${item.node_id}`}
                            className="text-[12px] font-medium truncate flex-1"
                            style={{
                              color: "var(--ink)",
                              textDecoration: "none",
                            }}
                          >
                            {item.node_name}
                          </Link>
                          <span
                            className="num text-[12px]"
                            style={{
                              color:
                                thresholdColor(metric, item.avg_value) ??
                                "var(--ink)",
                            }}
                          >
                            {formatValue(item.avg_value)}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 pl-6">
                          <span
                            className="text-[10.5px] flex-1 truncate"
                            style={{ color: "var(--ink-3)" }}
                          >
                            {item.locality} · max {formatValue(item.max_value)}{" "}
                            · <span className="num">{num(item.nb_points)}</span>{" "}
                            pts
                          </span>
                          <div style={{ width: 52 }}>
                            <Meter
                              value={item.avg_value}
                              max={max}
                              height={3}
                              color={
                                thresholdColor(metric, item.avg_value) ??
                                "var(--accent)"
                              }
                            />
                          </div>
                        </div>
                      </li>
                    ))}
                  </ul>
                );
              }}
            </QueryBoundary>
          </Panel>
        </div>
      </div>
    </div>
  );
}

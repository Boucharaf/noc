import { useState } from "react";
import { Link } from "react-router-dom";

import AvailabilityRanking from "../components/domain/AvailabilityRanking";
import NetworkVitals from "../components/domain/NetworkVitals";
import { FleetStatesChart } from "../components/domain/FleetInsights";
import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { LineChart } from "../components/charts";
import { Meter } from "../components/ui/Stat";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { useWindowStore, windowLabel } from "../store/ui";
import { METRIC_TYPES, metricMeta, thresholdColor } from "../lib/vocabulary";
import { bandwidth, dateTime, decimal, duration, num, pct, smartTime } from "../lib/format";
import {
  useNetworkKpi,
  useNetworkRanking,
  useNetworkSeries,
  useNodeStates,
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

export default function PerformancePage() {
  // Périmètre (localité, organisation, type) et période : barre unique
  // (AM-30, INC-28). La page n'a plus de « Périmètre » propre — une liste
  // plate de tous les sites — ni de second sélecteur de période.
  const hours = useWindowStore((s) => s.hours);
  // INC-27 : par défaut la même mesure que l'indicateur du haut.
  const [metric, setMetric] = useState("availability_pct");

  const nodeStates = useNodeStates();
  const network = useNetworkKpi();
  const series = useNetworkSeries({ metricType: metric, hours, sample: 15 });
  const top = useNetworkRanking({ metricType: metric, hours, sample: 15 });

  const meta = metricMeta(metric);
  const points = series.data?.points ?? [];

  const formatValue = (value) =>
    metric.startsWith("bandwidth")
      ? bandwidth(value)
      : `${decimal(value, meta.digits)}${meta.unit === "%" ? " %" : ` ${meta.unit}`}`;

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Performance réseau"
        subtitle={`Évolution des mesures du réseau · période ${windowLabel(hours)}`}
      />

      {/* Colonnes auto-ajustées : le nombre de tuiles dépend des mesures
          réellement collectées, la rangée ne doit pas rester à moitié vide. */}
      <div className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))" }}>
        <NetworkVitals
          data={network.data}
          expectedNodes={nodeStates.data?.total}
          compact
        />
      </div>

      <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
        Trois mesures différentes : la tuile « Parc en service » est la part
        des équipements en service <strong>à cet instant</strong> ; le classement est une moyenne{" "}
        <strong>sur la période</strong>, pondérée par le temps supervisé (référence du NOC) ; les
        « Indicateurs NetXMS » sont calculés <strong>par NetXMS</strong> et relayés tels quels.
      </p>

      <LinksAndAgency data={network.data} />

      <AvailabilityRanking />

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
              series.data
                ? `moyenne sur ${series.data.contributing_nodes} équipement(s) mesuré(s)${points.length ? ` · ${hours <= 48 ? "données détaillées" : "moyennes horaires"}` : ""}`
                : undefined
            }
          >
            <QueryBoundary
              query={series}
              compact
              minHeight={280}
        empty={(data) => !data?.points?.length}
              emptyMessage="Aucune mesure sur cette fenêtre"
              emptyHint="Aucune mesure disponible pour ce périmètre sur cette période."
            >
              <LineChart
                exportName={`performance-${metric}-${hours}h`}
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
                    pointCounts: points.map((point) => point.nb_nodes),
                    color: meta.color,
                    fill: true,
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
            // AM-17 : classement au 95e percentile (p95), sauf pour une mesure
            // où « plus haut est mieux » (disponibilité), classée en moyenne.
            subtitle={`${meta.higherIsBetter === true ? "moyenne" : "p95"} sur ${windowLabel(hours)} · top ${num(
              top.data?.length ?? 0,
            )}`}
            scope={{ period: "window" }}
            flush
          >
            <QueryBoundary
              query={top}
              compact
              emptyMessage="Aucun classement disponible"
            >
              {(items) => {
                const key = (item) =>
                  meta.higherIsBetter === true ? item.avg_value : item.p95_value ?? item.avg_value;
                const ranked = [...items].sort((left, right) =>
                  meta.higherIsBetter === true ? key(left) - key(right) : key(right) - key(left),
                );
                const max = Math.max(...ranked.map(key), 1);
                return (
                  <ul
                    className="divide-y"
                    style={{ borderColor: "var(--border)" }}
                  >
                    {ranked.map((item, index) => (
                      <li key={item.node_id} className="px-2.5 py-1.5">
                        <div className="flex items-baseline gap-2">
                          <span
                            className="num text-[12px]"
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
                                thresholdColor(metric, key(item)) ??
                                "var(--ink)",
                            }}
                          >
                            {formatValue(key(item))}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 pl-6">
                          <span
                            className="text-[12px] flex-1 truncate"
                            style={{ color: "var(--ink-3)" }}
                          >
                            {item.locality}
                            {meta.higherIsBetter !== true && item.p95_value != null
                              ? ` · moy. ${formatValue(item.avg_value)}`
                              : ""}{" "}
                            · max {formatValue(item.max_value)}{" "}
                            · <span className="num">{num(item.nb_points)}</span>{" "}
                            pts
                          </span>
                          <div style={{ width: 52 }}>
                            <Meter
                              value={key(item)}
                              max={max}
                              height={3}
                              color={
                                thresholdColor(metric, key(item)) ??
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

      <FleetStatesChart height={200} />
    </div>
  );
}

/**
 * Liens et disponibilité calculée par l'agence — publiés par NetXMS
 * (état des interfaces, attributs personnalisés des nœuds). Rien n'est
 * affiché quand aucune source ne les publie sur le périmètre.
 */
/**
 * Le nombre de pannes NetXMS est-il compatible avec le MTBF affiché ? Sur
 * une année au plus, N pannes par équipement imposent un MTBF ≤ 8 760 h / N.
 * Un écart d'un facteur 2 signale un double comptage (INC-39).
 */
function agencyIncoherent(agency) {
  if (!agency?.failures || !agency.nodes || !agency.avg_mtbf_h) return false;
  const perNode = agency.failures / agency.nodes;
  return perNode >= 1 && agency.avg_mtbf_h > (2 * 8760) / perNode;
}

function LinksAndAgency({ data }) {
  const links = data?.links;
  const agency = data?.agency_availability;
  if (!links && !agency) return null;
  return (
    <div className="grid grid-cols-12 gap-2.5">
      {links && (
        <div className={`col-span-12 ${agency ? "lg:col-span-7" : ""}`}>
          <Panel
            title="Liens et interfaces"
            scope={{ period: "live" }}
            sources="links"
            subtitle={`état réel des interfaces · ${num(links.nodes)} équipement(s) mesuré(s)${
              links.unmeasured_nodes
                ? ` · ${num(links.unmeasured_nodes)} non mesuré(s), exclus (non supervisés ou NetXMS sans réponse)`
                : ""
            }`}
          >
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat
                compact
                label="Liens surveillés actifs"
                // INC-08 : sans lien attendu, « Non surveillé » et non « — ».
                value={links.watched ? pct(links.watched_up_pct, 2) : "Non surveillé"}
                color={
                  links.watched
                    ? thresholdColor("availability_pct", links.watched_up_pct) ?? undefined
                    : "var(--ink-3)"
                }
                hint={
                  links.watched
                    ? `${num(links.watched - links.watched_down, "0")} / ${num(links.watched, "0")} attendus actifs`
                    : "aucun lien déclaré « attendu actif » dans NetXMS"
                }
              />
              <Stat
                compact
                label="Interfaces activées actives"
                value={links.enabled_up + links.enabled_down ? pct(links.enabled_up_pct, 1) : "Non mesuré"}
                hint={`${num(links.enabled_up, "0")} / ${num(links.enabled_up + links.enabled_down, "0")} · ports libres compris`}
              />
              <Stat
                compact
                label="Liens surveillés coupés"
                // Un « 0 » vert sans lien surveillé se lisait « aucun défaut ».
                value={links.watched ? num(links.watched_down, "0") : "Non surveillé"}
                color={
                  !links.watched ? "var(--ink-3)" : links.watched_down ? "var(--sev-high)" : undefined
                }
                hint={!links.watched ? "déclarer les liens attendus dans NetXMS" : undefined}
              />
              <Stat
                compact
                label="Capacité installée"
                value={links.nodes ? bandwidth(links.capacity_bps / 1e6) : "Non mesuré"}
                hint="débit nominal des interfaces en service — pas le débit utilisé"
              />
            </div>
          </Panel>
        </div>
      )}
      {agency && (
        <div className={`col-span-12 ${links ? "lg:col-span-5" : ""}`}>
          <Panel
            title="Indicateurs NetXMS (calcul de l'agence)"
            // INC-42 : ce n'est PAS la disponibilité officielle du NOC ; ce
            // sont les attributs calculés dans NetXMS, relayés tels quels.
            subtitle={`attributs NetXMS, non recalculés par le NOC · ${num(agency.nodes)} équipement(s)${
              agency.computed_at ? ` · calcul du ${dateTime(agency.computed_at)}` : ""
            }`}
          >
            {agencyIncoherent(agency) && (
              <p className="text-[12px] mb-2" style={{ color: "var(--sev-medium)" }} role="status">
                Incohérence : {num(agency.failures)} pannes pour {num(agency.nodes)} équipements (≈{" "}
                {num(agency.failures / agency.nodes)} chacun) ne correspond pas à un MTBF de{" "}
                {duration(agency.avg_mtbf_h * 60)}. Une même panne est probablement comptée à chaque
                alerte dans le calcul NetXMS. Le NOC compte, lui, des épisodes continus (Disponibilité,
                SLA).
              </p>
            )}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <Stat
                compact
                label="Disponibilité NetXMS"
                help="Disponibilité calculée par l'agence dans NetXMS (attribut perAvailability), moyenne simple des équipements qui la portent. Indicateur de contrôle : la disponibilité officielle du NOC est celle du journal historique, pondérée par le temps supervisé."
                value={pct(agency.avg_pct, 2)}
                color={thresholdColor("availability_pct", agency.avg_pct) ?? undefined}
              />
              <Stat
                compact
                label="MTTR moyen"
                value={duration(agency.avg_mttr_h != null ? agency.avg_mttr_h * 60 : null)}
                hint={`${num(agency.failures, "0")} pannes comptées`}
              />
              <Stat
                compact
                label="MTBF moyen"
                value={duration(agency.avg_mtbf_h != null ? agency.avg_mtbf_h * 60 : null)}
              />
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}

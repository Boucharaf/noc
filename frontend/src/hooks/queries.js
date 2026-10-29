/**
 * Toutes les requêtes de données de l'application.
 *
 * Centralisées pour une raison précise : la CADENCE de rafraîchissement est
 * une décision d'exploitation, pas un détail de composant.
 *
 * ─────────────────────────────────────────────────────────────────────────
 *  QUATRE RÉGIMES, ET POURQUOI LE QUATRIÈME EST NOUVEAU
 * ─────────────────────────────────────────────────────────────────────────
 *
 *   LIVE (20 s)        ce qui brûle maintenant : alertes, parc en panne,
 *                      vue d'ensemble. Ces appels lisent l'instantané Redis
 *                      du backend — ils ne touchent NI la base NI les outils
 *                      sources. Vingt secondes ne coûtent donc rien, et le
 *                      WebSocket pousse déjà les nouveautés : ce sondage
 *                      n'est qu'un filet si la socket est tombée.
 *
 *   OPERATIONAL (60 s) inventaire, interventions, maintenances.
 *
 *   ANALYTIC (5 min)   tendances et SLA, lus dans les agrégats journaliers.
 *                      Ils ne changent qu'une fois par jour : interroger
 *                      plus souvent ne renverrait que la même réponse.
 *
 *   ON_DEMAND (jamais) ⚠️ LES COURBES. Elles partent vers Zabbix ou
 *                      Centreon. Les mettre sur un sondage rendrait aux
 *                      outils de production toute la charge que cette
 *                      architecture leur retire — c'est exactement ce
 *                      qu'il ne faut pas faire. `refetchInterval: false`,
 *                      sans exception.
 *
 * `autoRefresh` (préférence utilisateur) coupe les trois premiers : sur une
 * liaison de secours, un sondage permanent coûte plus qu'il ne rapporte.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "../api/noc";
import { usePeriodStore, useUiStore } from "../store/ui";
import { useScopeParams } from "../store/scope";

export const REFRESH = Object.freeze({
  LIVE: 20_000,
  OPERATIONAL: 60_000,
  ANALYTIC: 300_000,
});

/** Intervalle effectif : `false` désactive le sondage (react-query). */
function useInterval(base) {
  const autoRefresh = useUiStore((s) => s.autoRefresh);
  return autoRefresh ? base : false;
}

/** Période courante du sélecteur de mois, sous forme de paramètres API. */
export function usePeriodParams() {
  const month = usePeriodStore((s) => s.month);
  const year = usePeriodStore((s) => s.year);
  return { month, year };
}

/* ================================================================== */
/* Vue d'ensemble — instantané Redis                                   */
/* ================================================================== */
/**
 * Synthèse du PÉRIMÈTRE courant (barre de périmètre) : parc, alertes des
 * outils, incidents iTop. `{ global: true }` ignore le périmètre — pour les
 * compteurs de navigation, qui portent sur tout le réseau.
 */
export function useOverview({ global = false } = {}) {
  const scope = useScopeParams();
  const params = global ? {} : scope;
  return useQuery({
    queryKey: ["overview", params],
    queryFn: () => api.overview.summary(params),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/**
 * Sites du parc.
 *
 * Remplace l'ancien `useReference` : il n'y a plus de référentiel
 * géographique dans le NOC. Un site est ce que les outils sources
 * déclarent (groupe « Site/… » côté Zabbix et Centreon, Location côté
 * iTop), et il se lit sur l'équipement.
 */
/**
 * Disponibilité par organisation (ministère, structure) : la « disponibilité
 * par ministère » du document métier. L'organisation est celle des CI iTop.
 */
export function useOrganisations() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["organisations", scope],
    queryFn: () => api.overview.organisations(scope),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/** Journal d'audit, du plus récent au plus ancien. */
export function useAuditLog({ action, limit = 100, offset = 0 } = {}) {
  const params = { action, limit, offset };
  return useQuery({
    queryKey: ["audit", params],
    queryFn: () => api.audit.list(params),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    placeholderData: (previous) => previous,
  });
}

export function useSites() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["sites", scope],
    queryFn: () => api.sites.list(scope),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useAlertsByTool() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["alerts", "by-tool", scope],
    queryFn: () => api.overview.alertsByTool(scope),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useAlertAges() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["alerts", "ages", scope],
    queryFn: () => api.overview.alertAges(scope),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useHourDistribution() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["alerts", "hour-distribution", scope],
    queryFn: () => api.overview.hourDistribution(scope),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/* ================================================================== */
/* Alertes                                                             */
/* ================================================================== */
/**
 * Alertes des OUTILS de supervision, dans le périmètre courant. Les
 * paramètres explicites de l'écran l'emportent sur le périmètre.
 */
export function useAlerts(params = {}) {
  const scope = useScopeParams();
  const query = { ...scope, ...params };
  return useQuery({
    queryKey: ["alerts", "list", query],
    queryFn: () => api.alerts.list(query),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useAlert(alertKey) {
  return useQuery({
    queryKey: ["alerts", "detail", alertKey],
    queryFn: () => api.alerts.get(alertKey),
    enabled: Boolean(alertKey),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Équipements                                                         */
/* ================================================================== */
/**
 * Inventaire. Accepte aussi les paramètres des anciens écrans (`q`,
 * `page_size`), et ajoute `items` — les nœuds sous leurs anciens noms de
 * champs (`node_id`, `locality`) — à côté de `nodes`, la forme native.
 */
export function useNodes(params = {}) {
  const { q, page, page_size: pageSize, ...rest } = params;
  const scope = useScopeParams();
  const query = { ...scope, ...rest };
  // La recherche saisie sur l'écran l'emporte sur celle de la barre.
  if (q !== undefined && q !== "") query.search = q;
  if (pageSize !== undefined && query.limit === undefined) query.limit = pageSize;
  if (page !== undefined && query.offset === undefined) {
    query.offset = (Math.max(1, Number(page)) - 1) * (query.limit ?? 200);
  }

  return useQuery({
    queryKey: ["nodes", "list", query],
    queryFn: () => api.nodes.list(query),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    select: (data) =>
      data && {
        ...data,
        page: Math.floor((data.offset ?? 0) / (data.limit || 1)) + 1,
        page_size: data.limit ?? pageSize ?? 200,
        pages: Math.max(1, Math.ceil((data.total ?? 0) / (data.limit ?? pageSize ?? 200))),
        items: (data.nodes ?? []).map((node) => ({
          ...node,
          node_id: node.id,
          locality: node.site,
          ip_address: node.ip,
          node_type: node.node_type ?? node.type,
          source_tools: Object.keys(node.sources ?? {}),
          open_incidents: node.alerts,
        })),
      },
  });
}

export function useNode(nodeId) {
  return useQuery({
    queryKey: ["nodes", "detail", nodeId],
    queryFn: () => api.nodes.get(nodeId),
    enabled: Boolean(nodeId),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    select: (node) =>
      node && {
        ...node,
        ip_address: node.ip_address ?? node.ip,
        locality: node.locality ?? node.site,
        node_type: node.node_type ?? node.type,
        source_tools: node.source_tools ?? Object.keys(node.sources ?? {}),
        source_refs:
          node.source_refs ??
          Object.entries(node.sources ?? {}).map(([source_tool, external_ref]) => ({
            source_tool,
            external_ref,
          })),
      },
  });
}

export function useNodeStates() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["nodes", "states", scope],
    queryFn: () => api.nodes.states(scope),
    refetchInterval: useInterval(REFRESH.LIVE),
    select: (data) =>
      data && {
        ...data,
        total: data.total ?? Object.values(data).reduce(
          (sum, value) => (typeof value === "number" ? sum + value : sum),
          0,
        ),
      },
  });
}

export function useNodeCoverage() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["nodes", "coverage", scope],
    queryFn: () => api.nodes.coverage(scope),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Réseau                                                              */
/* ================================================================== */
export function useNetworkSnapshot() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["network", "snapshot", scope],
    queryFn: () => api.metrics.snapshot(scope),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/**
 * Mini-courbes des tuiles : l'état du périmètre à chaque cycle des
 * dernières 24 h. Rend aussi des séries prêtes à tracer.
 */
export function useLiveTrend({ global = false } = {}) {
  const scope = useScopeParams();
  const params = global ? {} : scope;
  return useQuery({
    queryKey: ["trend", "live", params],
    queryFn: () => api.metrics.trend(params),
    refetchInterval: useInterval(REFRESH.LIVE),
    select: (data) => {
      const points = data?.points ?? [];
      const series = (field) => points.map((point) => point[field]);
      return {
        ...data,
        availability: series("availability_pct"),
        nodesDown: series("nodes_down"),
        alerts: series("alerts"),
        alertsCritical: series("alerts_critical"),
        incidents: series("incidents"),
        states: {
          up: series("nodes_up"),
          degraded: series("nodes_degraded"),
          down: series("nodes_down"),
          unknown: series("nodes_unknown"),
          maintenance: series("nodes_maintenance"),
        },
        times: points.map((point) => point.at),
      };
    },
  });
}

export function useNodesDown() {
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["network", "down", scope],
    queryFn: () => api.metrics.down(scope),
    select: (nodes) =>
      (nodes ?? []).map((node) => ({
        ...node,
        node_id: node.node_id ?? node.id,
        node_name: node.node_name ?? node.name,
        locality: node.locality ?? node.site,
        source_tools: node.source_tools ?? node.tools ?? [],
      })),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useTopNodes(options = 10) {
  // Les anciens écrans passent un objet ({ metricType, hours, limit }) :
  // transmis tel quel, il partait en `limit=[object Object]` et le backend
  // répondait 422.
  const limit = typeof options === "object" ? (options?.limit ?? 10) : options;
  const scope = useScopeParams();
  return useQuery({
    queryKey: ["network", "top", limit, scope],
    queryFn: () => api.metrics.top(limit, scope),
    select: (rows) =>
      (rows ?? []).map((node) => ({
        ...node,
        node_id: node.node_id ?? node.id,
        locality: node.locality ?? node.site,
        total_incidents: node.total_incidents ?? node.alerts,
        main_cause: node.main_cause ?? null,
      })),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/**
 * Courbe d'un équipement — ⚠️ INTERROGE L'OUTIL SOURCE.
 *
 * `refetchInterval: false` et un `staleTime` long, délibérément : chaque
 * appel part vers Zabbix ou Centreon. Le backend met la réponse en cache,
 * mais c'est au frontend de ne pas la redemander sans raison. L'exploitant
 * rafraîchit à la main s'il veut du neuf.
 *
 * Un échec ici est ORDINAIRE (outil indisponible) et ne doit pas être
 * réessayé en boucle : `retry: 1`.
 */
export function useNodeSeries(nodeId, { metric, period = "24h" } = {}) {
  return useQuery({
    queryKey: ["metrics", "node", nodeId, metric, period],
    queryFn: () => api.metrics.nodeSeries(nodeId, { metric, period }),
    select: (data) => metric ? (data?.points ?? []) : data,
    enabled: Boolean(nodeId),
    refetchInterval: false,
    staleTime: 60_000,
    retry: 1,
  });
}

// Fenêtres acceptées par GET /network/series, de la plus courte à la plus
// longue. Une fenêtre en heures est arrondie à la première qui la couvre.
const SERIES_PERIODS = [
  [1, "1h"],
  [6, "6h"],
  [24, "24h"],
  // Sans cette fenêtre, le choix « 3 j » des écrans était arrondi à 7 jours.
  [72, "3d"],
  [168, "7d"],
  [720, "30d"],
  [2160, "90d"],
];

export function periodFromHours(hours) {
  const match = SERIES_PERIODS.find(([limit]) => hours <= limit);
  return match ? match[1] : "1y";
}

/**
 * Courbe agrégée du réseau — même avertissement que ci-dessus.
 *
 * Rend une LISTE de points `{ time, value, nb_nodes }`, la forme
 * que lisent les écrans. Le backend renvoie un objet `{ points, … }` : le
 * passer tel quel faisait planter l'écran entier sur `.map`.
 *
 * `nb_nodes` est le nombre d'équipements ayant contribué à cette minute,
 * qui peut être inférieur à la taille totale de l'échantillon.
 */
export function useNetworkSeries({ metric, metricType, period, hours, sample, site, organisation, nodeType } = {}) {
  const metricKey = metric ?? metricType ?? "latency_ms";
  const periodKey = period ?? (hours ? periodFromHours(hours) : "24h");
  const sampleSize = sample ?? 12;
  const scope = useScopeParams();
  const params = {
    ...scope,
    metric: metricKey,
    period: periodKey,
    sample: sampleSize,
    site: site ?? scope.site,
    organisation,
    node_type: nodeType,
  };
  return useQuery({
    queryKey: ["metrics", "network", params],
    queryFn: () => api.metrics.networkSeries(params),
    select: (data) => ({
      points: (data?.points ?? []).map((point) => ({
        time: point.at,
        value: point.value,
        nb_nodes: point.contributing_nodes ?? data.contributing_nodes,
      })),
      sampled_nodes: data?.sampled_nodes ?? 0,
      population_nodes: data?.population_nodes ?? 0,
      measurable_nodes: data?.measurable_nodes ?? 0,
      contributing_nodes: data?.contributing_nodes ?? 0,
      source_errors: data?.source_errors ?? [],
    }),
    refetchInterval: false,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useNetworkRanking(options = {}) {
  const {
    metric,
    metricType,
    period,
    hours,
    sample,
    site,
    organisation,
    nodeType,
  } = options;
  const metricKey = metric ?? metricType ?? "latency_ms";
  const periodKey = period ?? (hours ? periodFromHours(hours) : "24h");
  const sampleSize = sample ?? 12;
  const scope = useScopeParams();
  const params = {
    ...scope,
    metric: metricKey,
    period: periodKey,
    sample: sampleSize,
    site: site ?? scope.site,
    organisation,
    node_type: nodeType,
  };
  return useQuery({
    queryKey: ["metrics", "network", params],
    queryFn: () => api.metrics.networkSeries(params),
    select: (data) => data?.node_ranking ?? [],
    refetchInterval: false,
    staleTime: 60_000,
    retry: 1,
  });
}

/* ================================================================== */
/* Tendances — agrégats journaliers                                    */
/* ================================================================== */
export function useKpiTrend(options = {}) {
  const { days = 30, site } =
    typeof options === "number" ? { days: options } : options;
  // Tendance du PÉRIMÈTRE : agrégats journaliers du site, de la province ou
  // de la région choisis (la recherche libre ne s'applique pas aux agrégats).
  const { search: _search, ...place } = useScopeParams();
  const params = { days, ...place, ...(site ? { site } : {}) };
  return useQuery({
    queryKey: ["kpi", "trend", params],
    queryFn: () => api.kpi.trend(params),
    select: (rows) =>
      (rows ?? []).map((row) => ({
        ...row,
        label: row.label ?? row.day,
        average_daily_alerts: row.average_daily_alerts ?? row.alerts,
        total_incidents: row.total_incidents ?? row.alerts,
        resolved: row.resolved ?? null,
      })),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useKpiMonthly(params) {
  const period = usePeriodParams();
  const { search: _search, ...place } = useScopeParams();
  const query = { ...period, ...place, ...params };
  return useQuery({
    queryKey: ["kpi", "monthly", query],
    queryFn: () => api.kpi.monthly(query),
    select: (data) => {
      if (!data) return data;
      const current = data.current ?? {};
      const delta = data.delta ?? {};
      return {
        ...data,
        // Les agrégats journaliers sont des MOYENNES par cycle de collecte :
        // nombre moyen d'alertes actives, d'alertes critiques actives et
        // d'équipements en panne à un instant donné. Ce ne sont pas des
        // décomptes d'incidents du mois — les nommer « incidents » faisait
        // lire 3,4 alertes simultanées comme « 3 incidents dans le mois ».
        kpi: {
          network_availability_pct: current.availability_pct,
          avg_active_alerts: current.avg_alerts,
          avg_active_critical: current.avg_critical,
          avg_nodes_down: current.avg_down,
          days_with_data: current.days_with_data,
          reliable: data.reliable,
        },
        // Pas de comparaison avec un mois précédent trop lacunaire : l'écart
        // mesurerait les trous de collecte, pas l'évolution du réseau.
        vs_previous_month: data.previous_reliable
          ? {
              availability_delta: delta.availability_pct,
              alerts_delta: delta.avg_alerts,
              critical_delta: delta.avg_critical,
            }
          : {},
      };
    },
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/**
 * Indicateurs d'incidents iTop de la période, dans le périmètre : volumes,
 * taux de résolution, équipements récurrents, causes, réouvertures, sites
 * et organisations les plus touchés.
 * ⚠️ Lit l'historique iTop : régime ANALYTIC, comme useSlaIncidents.
 */
export function useIncidentKpis({ days = 30 } = {}) {
  const { search: _search, ...place } = useScopeParams();
  const params = { days, ...place };
  return useQuery({
    queryKey: ["kpi", "incidents", params],
    queryFn: () => api.kpi.incidents(params),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
    placeholderData: (previous) => previous,
    staleTime: 120_000,
    retry: 1,
  });
}

export function useKpiSites({ days = 30, limit = 20, sort = "availability" } = {}) {
  const { search: _search, ...place } = useScopeParams();
  const params = { days, limit, sort, ...place };
  return useQuery({
    queryKey: ["kpi", "sites", params],
    queryFn: () => api.kpi.sites(params),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/* ================================================================== */
/* Engagements de service                                              */
/* ================================================================== */
/**
 * Incidents iTop ouverts qui vont manquer leur objectif de résolution (moins
 * de 25 % du délai restant) ou l'ont déjà manqué, dans le périmètre.
 *
 * Rafraîchi au régime LIVE et non ANALYTIC : c'est le seul indicateur SLA
 * sur lequel on peut encore agir, il perd tout intérêt s'il a cinq minutes
 * de retard. Lu sur l'instantané : aucun appel à iTop.
 */
export function useSlaAtRisk() {
  const { search: _search, ...place } = useScopeParams();
  return useQuery({
    queryKey: ["sla", "at-risk", place],
    queryFn: () => api.sla.atRisk(place),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useSlaTargets() {
  return useQuery({
    queryKey: ["sla", "targets"],
    queryFn: api.sla.targets,
    staleTime: 10 * 60_000,
  });
}

/**
 * Historique de disponibilité d'un équipement (journal, base du NOC).
 * Régime ANALYTIC : le journal ne change qu'aux changements d'état.
 */
export function useNodeHistory(nodeId, days = 30) {
  return useQuery({
    queryKey: ["history", "node", nodeId, days],
    queryFn: () => api.history.node(nodeId, days),
    enabled: Boolean(nodeId),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/** Équipements ou liens les moins disponibles sur la période, dans le périmètre. */
export function useHistoryRanking({ kind = "node", days = 30, limit = 15 } = {}) {
  const { search: _search, ...place } = useScopeParams();
  return useQuery({
    queryKey: ["history", "ranking", kind, days, limit, place],
    queryFn: () => api.history.ranking({ kind, days, limit, ...place }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/** Engagements contractuels iTop (SLT), comparés aux objectifs du NOC. */
export function useSlaContract() {
  return useQuery({
    queryKey: ["sla", "contract"],
    queryFn: api.sla.contract,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useUpdateSlaTarget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ severity, payload }) => api.sla.updateTarget(severity, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sla"] }),
  });
}

/* ================================================================== */
/* Interopérabilité                                                    */
/* ================================================================== */
export function useInterop() {
  const nodes = useNodes({ limit: 2000 });
  const alerts = useAlerts({ limit: 5000 });

  return useQuery({
    queryKey: ["interop", "status"],
    queryFn: api.interop.status,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    // Cet écran doit rester affichable quand tout le reste ne l'est plus :
    // on ne renonce pas au premier échec.
    retry: 3,
    select: (data) => {
      // Le décompte par outil n'est fiable que sur l'inventaire COMPLET :
      // tronqué à la page reçue, il sous-compterait les outils sans le dire.
      const completeInventory =
        nodes.data && (nodes.data.total ?? 0) <= (nodes.data.items?.length ?? 0);
      const configuredTools = (data?.tools ?? []).filter((tool) => tool.configured);
      return {
      ...data,
      // Lus par la barre du haut et la navigation (AppShell) : absents de la
      // réponse du backend, ils valaient `undefined` et l'indicateur
      // « outils en panne » affichait NaN.
      tools_total: configuredTools.length,
      tools_healthy: configuredTools.filter((tool) => tool.reachable && !tool.stale).length,
      tools: (data?.tools ?? []).map((tool) => {
        const toolNodes = nodes.data?.items?.filter((node) =>
          (node.source_tools ?? []).includes(tool.tool),
        ).length;
        const sourceAlerts = alerts.data?.alerts ?? [];
        const toolAlerts = sourceAlerts.filter(
          (alert) =>
            alert.tool === tool.tool &&
            (alert.kind ?? "technical") === "technical",
        ).length;
        const toolTickets = sourceAlerts.filter(
          (alert) => alert.tool === tool.tool && alert.kind === "itsm_ticket",
        ).length;
        const completeAlertList = alerts.data && !alerts.data.truncated;
        return {
          ...tool,
          // Un outil sans URL n'est pas « en erreur » : il n'est pas branché.
          state: tool.not_configured
            ? "not_configured"
            : tool.never_collected
              ? "unknown"
              : tool.reachable
                ? (tool.stale ? "stale" : "ok")
                : "error",
          last_run_at: tool.checked_at,
          detail: tool.not_configured
            ? "URL non renseignée dans .env — connecteur inactif"
            : tool.error ?? tool.version ?? "Aucun détail fourni",
          nb_nodes: tool.nb_nodes ?? (completeInventory ? toolNodes : null),
          nb_technical_alerts:
            tool.nb_technical_alerts ??
            (completeAlertList ? toolAlerts : null),
          nb_itsm_tickets: completeAlertList ? toolTickets : null,
          nb_metrics: tool.nb_metrics ?? null,
        };
      }),
      };
    },
  });
}

export function useMergeReport() {
  return useQuery({
    queryKey: ["interop", "merge"],
    queryFn: api.interop.merge,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Maintenance                                                         */
/* ================================================================== */
/**
 * Maintenances planifiées — changements iTop et maintenances Zabbix, lus par
 * le collecteur. Lecture seule : elles se planifient dans ces outils.
 * Rend `{ windows, counts, nodes_in_maintenance }`, dans le périmètre.
 */
export function useMaintenanceWindows(scope = "all", { global = false } = {}) {
  const place = useScopeParams();
  const params = { scope, ...(global ? {} : place) };
  return useQuery({
    queryKey: ["maintenance", params],
    queryFn: () => api.maintenance.list(params),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Suggestions de recherche                                            */
/* ================================================================== */
/** Préréglages : ce que chaque barre de recherche propose. */
export const SUGGEST_KINDS = {
  global: "region,province,site,node,incident",
  incident: "incident",
  alert: "alert,node",
  node: "node,site",
  maintenance: "maintenance,node",
  intervention: "intervention,node",
};

export function useSuggestions(term, preset) {
  const kinds = SUGGEST_KINDS[preset] ?? preset;
  const q = (term ?? "").trim();
  return useQuery({
    queryKey: ["suggest", kinds, q],
    queryFn: () => api.search.suggest({ q, kinds, limit: 8 }),
    enabled: Boolean(preset) && q.length >= 2,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
    retry: 0,
  });
}

/* ================================================================== */
/* Interventions — ordres de travail iTop                              */
/* ================================================================== */
export function useInterventions(status = "all") {
  const place = useScopeParams();
  const params = { status, ...place };
  return useQuery({
    queryKey: ["interventions", params],
    queryFn: () => api.interventions.list(params),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Comptes                                                             */
/* ================================================================== */
export function useUsers() {
  return useQuery({
    queryKey: ["users"],
    queryFn: api.users.list,
    staleTime: 5 * 60_000,
  });
}

export function useUserActions() {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });
  return {
    create: useMutation({ mutationFn: api.users.create, onSuccess: invalidate }),
    update: useMutation({
      mutationFn: ({ userId, payload }) => api.users.update(userId, payload),
      onSuccess: invalidate,
    }),
    deactivate: useMutation({ mutationFn: api.users.deactivate, onSuccess: invalidate }),
    resetPin: useMutation({
      mutationFn: ({ userId, pin }) => api.users.resetPin(userId, pin),
      onSuccess: invalidate,
    }),
    resetPassword: useMutation({
      mutationFn: ({ userId, password }) => api.users.resetPassword(userId, password),
    }),
  };
}

/** Courriel d'alerte : configuration SMTP et destinataires effectifs. */
export function useEmailStatus() {
  return useQuery({
    queryKey: ["notifications", "email"],
    queryFn: api.notifications.emailStatus,
    staleTime: 60_000,
  });
}

export function useSendTestEmail() {
  return useMutation({ mutationFn: (to) => api.notifications.sendTestEmail(to) });
}

/* ================================================================== */
/* Compatibilité avec les écrans de la version précédente              */
/* ================================================================== */
/**
 * Ces hooks portent les anciens noms et reconstituent les anciennes formes
 * de données à partir des nouvelles sources. Ils existent pour que les
 * quinze écrans déjà écrits continuent de fonctionner sans être réécrits
 * un par un.
 *
 * CE N'EST PAS DE LA DETTE GRATUITE : chaque adaptation est explicite, et
 * celles qui ne peuvent PAS être reconstituées le disent franchement au
 * lieu de rendre un tableau vide qui se lirait « rien à signaler ». Les
 * concepts disparus sont ceux qui n'existaient que dans l'entrepôt
 * supprimé — localités géolocalisées, ministères, incidents numérotés.
 *
 * À reprendre écran par écran, en remplaçant chaque appel par le hook
 * natif indiqué en commentaire.
 */

/**
 * Une alerte, sous la forme d'« incident » qu'attendent les anciens écrans
 * (IncidentTable, IncidentDrawer, mur d'alertes).
 *
 * Les champs natifs sont CONSERVÉS : on ajoute les anciens noms, on n'en
 * retire aucun. Ce qui n'a pas d'équivalent (MTTA, ministère, région) reste
 * absent et s'affiche « — » plutôt qu'inventé.
 */
function toIncident(alert) {
  if (!alert) return alert;
  const detectedAt = alert.since ? Date.parse(alert.since) : NaN;
  return {
    ...alert,
    id: alert.key,
    detected_at: alert.since,
    age_minutes: Number.isNaN(detectedAt) ? null : Math.max(0, (Date.now() - detectedAt) / 60_000),
    status: alert.resolved_at ? "resolved" : alert.acknowledged ? "acknowledged" : "open",
    description: alert.message ?? alert.description,
    locality: alert.site,
    node_id: alert.node_key,
    source_tool: alert.tool,
    external_id: alert.ref,
    itop_ticket_ref: alert.ticket_ref,
  };
}

/** Ancien résumé d'alertes, dérivé de l'instantané. */
export function useAlertSummary() {
  const overview = useOverview();
  const data = overview.data;
  // Décomptes par état DU PÉRIMÈTRE : /nodes/states porte sur tout le parc,
  // et mêlerait les équipements de la région choisie à ceux du pays.
  const nodeStates = data?.nodes_by_state;

  return {
    ...overview,
    data: data
      ? {
          total_open: data.alerts_total ?? 0,
          unacknowledged: data.alerts_unacknowledged ?? 0,
          critical: data.alerts_by_severity?.critical ?? 0,
          high: data.alerts_by_severity?.high ?? 0,
          medium: data.alerts_by_severity?.medium ?? 0,
          low: data.alerts_by_severity?.low ?? 0,
          total: data.nodes_total ?? 0,
          // Décomptes par état : `null` tant que /nodes/states n'a pas
          // répondu (ou a échoué). Un « 0 en panne » affiché à la place
          // d'une donnée manquante se lit « tout va bien ».
          up: nodeStates ? nodeStates.up ?? 0 : null,
          down: nodeStates ? nodeStates.down ?? 0 : null,
          degraded: nodeStates ? nodeStates.degraded ?? 0 : null,
          silent: nodeStates ? nodeStates.silent ?? 0 : null,
          maintenance: nodeStates ? nodeStates.maintenance ?? 0 : null,
          localities_affected: data.sites_impacted ?? null,
          // L'ancienneté de la plus vieille alerte non acquittée n'est plus
          // calculée côté serveur : la liste d'alertes est déjà triée par
          // gravité puis par date, l'écran la lit sur sa dernière ligne.
          oldest_unacknowledged_at: null,
          snapshot_age_s: data.snapshot_age_s,
          stale: data.stale,
          incidents_total: data.incidents_total ?? null,
          incidents_critical: data.incidents_critical ?? null,
          incidents_unassigned: data.incidents_unassigned ?? null,
        }
      : undefined,
  };
}

/** Alertes ouvertes, en liste plate comme l'attendaient les anciens écrans. */
export function useOpenAlerts({ limit = 50, ...rest } = {}) {
  const query = useAlerts({ limit, acknowledged: false, ...rest });
  return { ...query, data: query.data?.alerts?.map(toIncident) };
}

/**
 * Indicateurs réseau.
 *
 * Le paramètre `hours` des anciens appels est ignoré : cet écran montre
 * l'instant présent, pas une moyenne glissante. Le calculer sur une fenêtre
 * demanderait d'interroger les outils sources à chaque rafraîchissement.
 */
export function useNetworkKpi() {
  const query = useNetworkSnapshot();
  const data = query.data;
  return {
    ...query,
    data: data
      ? {
          ...data,
          availability_pct: data.fleet_availability_pct,
          // « Remontent » = les équipements dont un outil dit quelque chose.
          // Les muets sont précisément ceux qui ne remontent plus rien.
          // Un état « inconnu » (conflit entre outils, CMDB seule) ne remonte
          // pas davantage de mesure qu'un équipement muet.
          nodes_reporting:
            data.nodes_total == null
              ? null
              : data.nodes_total - (data.nodes_unknown ?? 0),
          // Disponibilité : déduite de l'état du parc. Latence, pertes,
          // débits, CPU… : dernières valeurs relevées par le collecteur
          // auprès des outils qui les fournissent (Zabbix, Centreon), et
          // listées par le backend. Une métrique absente de la liste n'est
          // pas à zéro : aucun outil branché ne la mesure dans ce périmètre.
          metric_types_available: [
            ...(data.fleet_availability_pct != null ? ["availability_pct"] : []),
            ...(data.metric_types_available ?? []),
          ],
        }
      : undefined,
  };
}

/** Incidents, devenus alertes — voir l'en-tête de api/noc.js. */
export function useIncidents(params = {}) {
  const {
    page = 1,
    page_size: pageSize = 50,
    severity,
    kind,
    source_tool: tool,
    site,
    locality_id: legacySite,
    acknowledged,
    exclude_itsm: excludeItsm = false,
    ...filters
  } = params;
  const acknowledgedFilter =
    acknowledged === undefined
      ? undefined
      : typeof acknowledged === "boolean"
        ? acknowledged
        : acknowledged === "true";
  const scope = useScopeParams();
  const query = useQuery({
    queryKey: ["alerts", "incidents", params, scope],
    queryFn: () =>
      api.alerts.list({
        ...scope,
        severity,
        kind,
        tool,
        site: site ?? legacySite ?? scope.site,
        acknowledged: acknowledgedFilter,
        limit: 5000,
      }),
    refetchInterval: useInterval(REFRESH.LIVE),
    select: (data) => {
      let rows = (data?.alerts ?? []).map(toIncident);
      // Écran Alertes : les tickets iTop sont des INCIDENTS, ils ont leur écran.
      if (excludeItsm) rows = rows.filter((row) => row.kind !== "itsm_ticket");
      if (filters.status) rows = rows.filter((row) => row.status === filters.status);
      if (filters.node_code) {
        const needle = filters.node_code.toLowerCase();
        rows = rows.filter((row) =>
          [row.node_name, row.node_key, row.message, row.description]
            .filter(Boolean)
            .some((value) => String(value).toLowerCase().includes(needle)),
        );
      }
      if (filters.cause_category) {
        rows = rows.filter(
          (row) => row.cause_category === filters.cause_category || row.cause_label === filters.cause_category,
        );
      }
      if (filters.date_from) rows = rows.filter((row) => row.detected_at >= filters.date_from);
      if (filters.date_to) rows = rows.filter((row) => row.detected_at <= filters.date_to);
      const total = rows.length;
      const first = (Math.max(1, Number(page)) - 1) * pageSize;
      return {
        items: rows.slice(first, first + pageSize),
        total,
        page: Math.max(1, Number(page)),
        page_size: pageSize,
        pages: Math.max(1, Math.ceil(total / pageSize)),
      };
    },
  });
  return {
    ...query,
    data: query.data,
  };
}

export function useIncident(alertKey) {
  const query = useAlert(alertKey);
  return { ...query, data: query.data ? toIncident(query.data) : undefined };
}

export function useCoverage() {
  const coverage = useNodeCoverage();
  const nodes = useNodes({ limit: 2000 });
  return {
    ...coverage,
    isLoading: coverage.isLoading || nodes.isLoading,
    isPending: coverage.isPending || nodes.isPending,
    data: coverage.data && nodes.data
      ? (() => {
          const inventory = nodes.data.items ?? [];
          const total = nodes.data.total ?? inventory.length;
          // Calculée sur la page reçue, la couverture n'est juste que si la
          // page contient tout le parc.
          const complete = inventory.length >= total;
          // « Supervisé » = vu par au moins un outil de SUPERVISION. iTop est
          // un référentiel : un équipement connu de la seule CMDB est
          // précisément un équipement non supervisé. Compter toute source
          // donnait une couverture de 100 % par construction.
          const isMonitored = (node) =>
            (node.source_tools ?? []).some((tool) => tool !== "itop");
          const monitored = inventory.filter(isMonitored).length;
          const bySite = Object.values(
            inventory.reduce((groups, node) => {
              const site = node.locality || "Site non renseigné";
              const row = groups[site] ?? {
                locality: site,
                locality_id: site,
                region: null,
                ministry: null,
                total_assets: 0,
                monitored_assets: 0,
                unmonitored_assets: 0,
              };
              row.total_assets += 1;
              if (isMonitored(node)) row.monitored_assets += 1;
              else row.unmonitored_assets += 1;
              groups[site] = row;
              return groups;
            }, {}),
          ).map((row) => ({
            ...row,
            coverage_pct: row.total_assets
              ? Math.round((1000 * row.monitored_assets) / row.total_assets) / 10
              : null,
          }));
          return {
            total_assets: total,
            monitored_assets: complete ? monitored : null,
            unmonitored_assets: complete ? Math.max(0, total - monitored) : null,
            coverage_pct: complete && total ? Math.round((1000 * monitored) / total) / 10 : null,
            as_of: null,
            source: "instantané de collecte",
            is_complete_inventory: complete,
            by_locality: bySite,
          };
        })()
      : undefined,
  };
}

export function useCoverageTrend({ days = 30 } = {}) {
  return useKpiTrend({ days });
}

export function useKpiSummary(params) {
  return useKpiMonthly(params);
}

/**
 * Sites, anciennement localités. Les agrégats journaliers portent une
 * moyenne d'alertes actives, pas un décompte d'incidents historiques.
 */
export function useKpiLocalities(params = {}) {
  const query = useKpiSites(
    typeof params === "number"
      ? { limit: params, sort: "alerts" }
      : { ...params, sort: params.sort ?? "alerts" },
  );
  return {
    ...query,
    data: query.data?.map((row) => ({
      ...row,
      locality: row.site,
      locality_id: row.site,
      average_alerts: row.avg_alerts,
      critical: row.avg_critical ?? null,
    })),
  };
}

/** Alertes actives d'un équipement — déjà portées par sa fiche. */
export function useNodeIncidents(nodeId) {
  const query = useNode(nodeId);
  // Alertes brutes de l'instantané (`message`, `since`, `tool`) : même
  // adaptation que la file d'alertes, sans quoi la fiche affiche des tirets.
  return { ...query, data: (query.data?.active_alerts ?? []).map(toIncident) };
}

/**
 * Dernière valeur de chaque métrique d'un équipement.
 *
 * Interroge l'outil source, et rend la dernière valeur de la série sur une
 * heure : il n'y a plus de table de « dernières valeurs » côté NOC,
 * puisqu'aucune métrique n'y est recopiée.
 */
export function useNodeLatest(nodeId) {
  return useQuery({
    queryKey: ["metrics", "node", nodeId, "latest"],
    queryFn: () => api.metrics.nodeLatest(nodeId),
    select: (data) => data?.latest,
    enabled: Boolean(nodeId),
    refetchInterval: false,
    staleTime: 60_000,
    retry: 1,
  });
}

/* ================================================================== */
/* Territoire — région > province > site > nœud                        */
/* ================================================================== */
export function useGeoOptions() {
  return useQuery({
    queryKey: ["geo", "options"],
    queryFn: api.geo.options,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    staleTime: 60_000,
  });
}

/**
 * Le périmètre et ses subdivisions immédiates (régions, provinces, sites
 * ou équipements selon la profondeur). `scope` explicite pour afficher un
 * autre niveau que celui de la barre (fil d'Ariane, survol de carte).
 */
export function useGeoBreakdown(scopeOverride) {
  const current = useScopeParams();
  const params = scopeOverride ?? current;
  return useQuery({
    queryKey: ["geo", "breakdown", params],
    queryFn: () => api.geo.breakdown(params),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useGeoSite(site) {
  return useQuery({
    queryKey: ["geo", "site", site],
    queryFn: () => api.geo.site(site),
    enabled: Boolean(site),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/* ================================================================== */
/* Incidents iTop                                                      */
/* ================================================================== */
export function useItopIncidents(params = {}, { global = false } = {}) {
  const scope = useScopeParams();
  const query = { ...(global ? {} : scope), ...params };
  return useQuery({
    queryKey: ["incidents", "list", query],
    queryFn: () => api.itopIncidents.list(query),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/**
 * Historique iTop paginé (tickets ouverts sur la période, clos ou non).
 * `params` à null : requête désactivée (onglet non affiché).
 */
export function useItopIncidentHistory(params = {}) {
  const scope = useScopeParams();
  const query = { ...scope, ...params };
  return useQuery({
    queryKey: ["incidents", "history", query],
    queryFn: () => api.itopIncidents.history(query),
    enabled: params !== null,
    refetchInterval: useInterval(REFRESH.ANALYTIC),
    placeholderData: (previous) => previous,
    staleTime: 60_000,
    retry: 1,
  });
}

export function useItopIncident(incidentKey) {
  return useQuery({
    queryKey: ["incidents", "detail", incidentKey],
    queryFn: () => api.itopIncidents.get(incidentKey),
    enabled: Boolean(incidentKey),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/**
 * SLA des incidents iTop, ventilés par région, province, site ou nœud.
 * ⚠️ Lit l'historique chez iTop : régime ANALYTIC, pas de sondage rapide.
 */
export function useSlaIncidents({
  groupBy = "region",
  days = 30,
  startAt,
  endAt,
  global = false,
} = {}) {
  const scope = useScopeParams();
  const { search: _search, ...place } = scope;
  const params = {
    group_by: groupBy,
    days,
    // Bornes explicites (mois d'un rapport) : elles l'emportent sur `days`.
    ...(startAt ? { start_at: startAt, end_at: endAt } : {}),
    ...(global ? {} : place),
  };
  return useQuery({
    queryKey: ["sla", "incidents", params],
    queryFn: () => api.itopIncidents.sla(params),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
    // Changer de période ne vide pas l'écran le temps qu'iTop réponde : les
    // chiffres précédents restent affichés (isPlaceholderData) et la page
    // signale la mise à jour.
    placeholderData: (previous) => previous,
    staleTime: 120_000,
    retry: 1,
  });
}

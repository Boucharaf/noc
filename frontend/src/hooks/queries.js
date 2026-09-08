/**
 * Toutes les requêtes de données de l'application.
 *
 * Centralisées pour une raison précise : la CADENCE de rafraîchissement
 * est une décision d'exploitation, pas un détail de composant. Trois
 * régimes cohabitent, et les mélanger produit soit un mur d'alertes en
 * retard de cinq minutes, soit un agrégat mensuel recalculé toutes les
 * dix secondes pour rien :
 *
 *   LIVE (20 s)   — ce qui brûle maintenant : alertes, résumé, parc en
 *                   panne. Le veilleur backend tourne à 30 s, le
 *                   WebSocket pousse déjà les nouveautés ; ce poll n'est
 *                   qu'un filet de sécurité si la socket est tombée.
 *   OPERATIONAL   — files d'incidents, inventaire, interventions : 60 s.
 *   ANALYTIQUE    — KPI mensuels, SLA, tendances : 5 min, exactement le
 *                   CACHE_TTL du backend. Interroger plus souvent ne
 *                   renverrait que la même réponse Redis.
 *
 * `autoRefresh` (préférence utilisateur) coupe les trois : sur une
 * liaison de secours, un poll permanent coûte plus qu'il ne rapporte.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as api from "../api/noc";
import { usePeriodStore, useUiStore } from "../store/ui";

export const REFRESH = Object.freeze({
  LIVE: 20_000,
  OPERATIONAL: 60_000,
  ANALYTIC: 300_000,
});

/** Intervalle effectif : `false` désactive le poll (react-query). */
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
/* Référentiel                                                         */
/* ================================================================== */
export function useReference() {
  return useQuery({
    queryKey: ["geo", "reference"],
    queryFn: api.geo.reference,
    // Le référentiel ne bouge qu'au rythme des découvertes de l'ETL.
    staleTime: 10 * 60_000,
  });
}

/* ================================================================== */
/* Temps réel — alertes et santé du parc                               */
/* ================================================================== */
export function useAlertSummary(localityId) {
  return useQuery({
    queryKey: ["alerts", "summary", localityId ?? null],
    queryFn: () => api.alerts.summary({ locality_id: localityId }),
    refetchInterval: useInterval(REFRESH.LIVE),
    staleTime: 10_000,
  });
}

export function useOpenAlerts({ limit = 40, localityId } = {}) {
  return useQuery({
    queryKey: ["alerts", "open", limit, localityId ?? null],
    queryFn: () => api.alerts.open({ limit, locality_id: localityId }),
    refetchInterval: useInterval(REFRESH.LIVE),
    staleTime: 10_000,
  });
}

export function useRecentAlerts(limit = 15) {
  return useQuery({
    queryKey: ["alerts", "recent", limit],
    queryFn: () => api.alerts.recent({ limit }),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useNodeStates(localityId) {
  return useQuery({
    queryKey: ["nodes", "states", localityId ?? null],
    queryFn: () => api.nodes.states({ locality_id: localityId }),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useNodesDown(localityId) {
  return useQuery({
    queryKey: ["metrics", "nodes-down", localityId ?? null],
    queryFn: () => api.metrics.nodesDown({ locality_id: localityId }),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useNetworkKpi({ hours = 24, localityId } = {}) {
  return useQuery({
    queryKey: ["metrics", "network", hours, localityId ?? null],
    queryFn: () => api.metrics.network({ hours, locality_id: localityId }),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useNetworkSeries({ metricType, hours = 24, localityId, ministryId, enabled = true }) {
  return useQuery({
    queryKey: ["metrics", "network-series", metricType, hours, localityId ?? null, ministryId ?? null],
    queryFn: () =>
      api.metrics.networkSeries({
        metric_type: metricType,
        hours,
        locality_id: localityId,
        ministry_id: ministryId,
      }),
    enabled: Boolean(metricType) && enabled,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useTopNodes({ metricType, hours = 24, limit = 10, localityId, enabled = true }) {
  return useQuery({
    queryKey: ["metrics", "top", metricType, hours, limit, localityId ?? null],
    queryFn: () =>
      api.metrics.top({ metric_type: metricType, hours, limit, locality_id: localityId }),
    enabled: Boolean(metricType) && enabled,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Incidents                                                            */
/* ================================================================== */
export function useIncidents(filters, { enabled = true } = {}) {
  return useQuery({
    queryKey: ["incidents", "list", filters],
    queryFn: () => api.incidents.list(filters),
    enabled,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    // Garde la page précédente affichée pendant le chargement de la
    // suivante : sans ça, le tableau se vide à chaque changement de page
    // et la position de lecture est perdue.
    placeholderData: (previous) => previous,
  });
}

export function useIncident(incidentId) {
  return useQuery({
    queryKey: ["incidents", "detail", incidentId],
    queryFn: () => api.incidents.detail(incidentId),
    enabled: Boolean(incidentId),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useWorkload({ enabled = true } = {}) {
  return useQuery({
    queryKey: ["incidents", "workload"],
    queryFn: api.incidents.workload,
    enabled,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/**
 * Invalidation après une action sur un incident.
 *
 * Volontairement large : acquitter un incident change la file, les
 * compteurs du bandeau, la charge par intervenant, l'état de
 * l'équipement et les KPI du mois. Invalider finement chacune de ces
 * clés serait plus « propre » et laisserait immanquablement un compteur
 * en retard — le coût d'un refetch de quelques agrégats est négligeable
 * devant celui d'un écran qui ment.
 */
function useIncidentInvalidation() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["incidents", "alerts", "nodes", "kpi", "sla", "metrics"]) {
      queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function useIncidentActions() {
  const invalidate = useIncidentInvalidation();
  const options = { onSuccess: invalidate };

  return {
    acknowledge: useMutation({ mutationFn: (id) => api.incidents.acknowledge(id), ...options }),
    resolve: useMutation({
      mutationFn: ({ id, notes }) => api.incidents.resolve(id, notes),
      ...options,
    }),
    assign: useMutation({
      mutationFn: ({ id, userId, note }) => api.incidents.assign(id, userId, note),
      ...options,
    }),
    escalate: useMutation({
      mutationFn: ({ id, userId, reason }) => api.incidents.escalate(id, userId, reason),
      ...options,
    }),
    comment: useMutation({
      mutationFn: ({ id, note }) => api.incidents.comment(id, note),
      ...options,
    }),
    createManual: useMutation({ mutationFn: api.incidents.createManual, ...options }),
  };
}

/* ================================================================== */
/* Équipements                                                          */
/* ================================================================== */
export function useNodes(filters) {
  return useQuery({
    queryKey: ["nodes", "list", filters],
    queryFn: () => api.nodes.list(filters),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    placeholderData: (previous) => previous,
  });
}

export function useNode(nodeId) {
  return useQuery({
    queryKey: ["nodes", "detail", nodeId],
    queryFn: () => api.nodes.detail(nodeId),
    enabled: Boolean(nodeId),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useNodeIncidents(nodeId, limit = 20) {
  return useQuery({
    queryKey: ["nodes", "incidents", nodeId, limit],
    queryFn: () => api.nodes.incidents(nodeId, { limit }),
    enabled: Boolean(nodeId),
  });
}

export function useNodeSeries(nodeId, metricType, hours) {
  return useQuery({
    queryKey: ["metrics", "node-series", nodeId, metricType, hours],
    queryFn: () => api.metrics.nodeSeries(nodeId, { metric_type: metricType, hours }),
    enabled: Boolean(nodeId && metricType),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useNodeLatest(nodeId) {
  return useQuery({
    queryKey: ["metrics", "node-latest", nodeId],
    queryFn: () => api.metrics.nodeLatest(nodeId),
    enabled: Boolean(nodeId),
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

/* ================================================================== */
/* KPI mensuels                                                         */
/* ================================================================== */
function analyticQuery(key, queryFn, extra = {}) {
  return {
    queryKey: key,
    queryFn,
    // Aligné sur CACHE_TTL du backend (300 s) : interroger plus souvent
    // ne ferait que relire la même réponse Redis.
    staleTime: REFRESH.ANALYTIC,
    ...extra,
  };
}

export function useKpiSummary() {
  const period = usePeriodParams();
  return useQuery(analyticQuery(["kpi", "summary", period], () => api.kpi.summary(period)));
}

export function useKpiTrend(months = 6) {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "trend", period, months], () =>
      api.kpi.trend({ ...period, months }),
    ),
  );
}

export function useKpiLocalities(limit = 10) {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "localities", period, limit], () =>
      api.kpi.localities({ ...period, limit }),
    ),
  );
}

export function useKpiLocalitiesMap() {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "localities-map", period], () => api.kpi.localitiesMap(period)),
  );
}

export function useKpiNodes({ limit = 10, localityId } = {}) {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "nodes", period, limit, localityId ?? null], () =>
      api.kpi.nodes({ ...period, limit, locality_id: localityId }),
    ),
  );
}

export function useKpiRecurrent(minCount = 3) {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "recurrent", period, minCount], () =>
      api.kpi.recurrent({ ...period, min_count: minCount }),
    ),
  );
}

export function useKpiCauses() {
  const period = usePeriodParams();
  return useQuery(analyticQuery(["kpi", "causes", period], () => api.kpi.causes(period)));
}

export function useKpiHourDistribution() {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "hours", period], () => api.kpi.hourDistribution(period)),
  );
}

export function useKpiMinistries() {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(["kpi", "ministries", period], () => api.kpi.ministries(period)),
  );
}

export function useLocalityNodes(localityId) {
  const period = usePeriodParams();
  return useQuery(
    analyticQuery(
      ["kpi", "locality-nodes", localityId, period],
      () => api.kpi.localityNodes(localityId, period),
      { enabled: Boolean(localityId) },
    ),
  );
}

/* ================================================================== */
/* SLA, couverture, interopérabilité                                   */
/* ================================================================== */
export function useSla() {
  const period = usePeriodParams();
  return useQuery(analyticQuery(["sla", period], () => api.sla.get(period)));
}

export function useSlaTargets() {
  return useQuery({ queryKey: ["sla", "targets"], queryFn: api.sla.targets, staleTime: 600_000 });
}

export function useUpdateSlaTarget() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ severity, payload }) => api.sla.updateTarget(severity, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["sla"] }),
  });
}

export function useCoverage() {
  return useQuery({
    queryKey: ["coverage", "summary"],
    queryFn: api.coverage.summary,
    staleTime: REFRESH.ANALYTIC,
  });
}

export function useCoverageTrend(days = 30) {
  return useQuery({
    queryKey: ["coverage", "trend", days],
    queryFn: () => api.coverage.trend({ days }),
    staleTime: REFRESH.ANALYTIC,
  });
}

export function useInterop({ enabled = true } = {}) {
  const period = usePeriodParams();
  return useQuery({
    queryKey: ["interop", period],
    queryFn: () => api.interop.status(period),
    enabled,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health.check,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    retry: false,
  });
}

/* ================================================================== */
/* Maintenance                                                          */
/* ================================================================== */
export function useMaintenanceWindows({ onlyActive = false, limit = 100 } = {}) {
  return useQuery({
    queryKey: ["maintenance", onlyActive, limit],
    queryFn: () => api.maintenance.list({ only_active: onlyActive, limit }),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useMaintenanceActions() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["maintenance"] });
    // Une fenêtre de maintenance neutralise les alertes et change l'état
    // des équipements couverts : le parc doit être relu.
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
  };
  return {
    create: useMutation({ mutationFn: api.maintenance.create, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: api.maintenance.remove, onSuccess: invalidate }),
  };
}

/* ================================================================== */
/* Terrain                                                              */
/* ================================================================== */
export function useFieldInterventions(statusFilter) {
  return useQuery({
    queryKey: ["field", statusFilter ?? null],
    queryFn: () => api.field.list({ status_filter: statusFilter }),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useFieldActions() {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["field"] });
  return {
    create: useMutation({ mutationFn: api.field.create, onSuccess: invalidate }),
    updateStatus: useMutation({
      mutationFn: ({ id, status }) => api.field.updateStatus(id, status),
      onSuccess: invalidate,
    }),
    submitReport: useMutation({
      mutationFn: ({ id, payload }) => api.field.submitReport(id, payload),
      onSuccess: invalidate,
    }),
  };
}

/* ================================================================== */
/* Comptes                                                              */
/* ================================================================== */
export function useUsers() {
  return useQuery({ queryKey: ["users"], queryFn: api.users.list, staleTime: 60_000 });
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
  };
}

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
import { useAuthStore } from "../store/auth";
import { usePeriodStore, useUiStore } from "../store/ui";

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
export function useOverview() {
  return useQuery({
    queryKey: ["overview"],
    queryFn: api.overview.summary,
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
export function useSites() {
  return useQuery({
    queryKey: ["sites"],
    queryFn: api.sites.list,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useAlertsBySeverity() {
  return useQuery({
    queryKey: ["alerts", "by-severity"],
    queryFn: api.overview.alertsBySeverity,
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useAlertsByTool() {
  return useQuery({
    queryKey: ["alerts", "by-tool"],
    queryFn: api.overview.alertsByTool,
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useHourDistribution() {
  return useQuery({
    queryKey: ["alerts", "hour-distribution"],
    queryFn: api.overview.hourDistribution,
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/* ================================================================== */
/* Alertes                                                             */
/* ================================================================== */
export function useAlerts(params = {}) {
  return useQuery({
    queryKey: ["alerts", "list", params],
    queryFn: () => api.alerts.list(params),
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

/**
 * Actions sur une alerte.
 *
 * Toutes invalident `["alerts"]` en bloc plutôt que la seule fiche : un
 * acquittement change aussi les compteurs de la vue d'ensemble et la
 * répartition par gravité. Invalider finement obligerait à tenir à jour la
 * liste des écrans concernés à chaque nouvelle action.
 */
export function useAlertActions() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
    queryClient.invalidateQueries({ queryKey: ["overview"] });
  };

  return {
    acknowledge: useMutation({
      mutationFn: ({ alertKey, note }) => api.alerts.acknowledge(alertKey, note),
      onSuccess: invalidate,
    }),
    assign: useMutation({
      mutationFn: ({ alertKey, assigneeId, note }) =>
        api.alerts.assign(alertKey, assigneeId, note),
      onSuccess: invalidate,
    }),
    resolve: useMutation({
      mutationFn: ({ alertKey, cause, note }) =>
        api.alerts.resolve(alertKey, cause, note),
      onSuccess: invalidate,
    }),
    addNote: useMutation({
      mutationFn: ({ alertKey, note }) => api.alerts.addNote(alertKey, note),
      onSuccess: invalidate,
    }),
    createManual: useMutation({
      mutationFn: (payload) => api.manualIncidents.create(payload),
      onSuccess: invalidate,
    }),
    resolveManual: useMutation({
      mutationFn: (id) => api.manualIncidents.resolve(id),
      onSuccess: invalidate,
    }),
  };
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
  const { q, page_size: pageSize, ...rest } = params;
  const query = { ...rest };
  if (q !== undefined && query.search === undefined) query.search = q;
  if (pageSize !== undefined && query.limit === undefined) query.limit = pageSize;

  return useQuery({
    queryKey: ["nodes", "list", query],
    queryFn: () => api.nodes.list(query),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    select: (data) =>
      data && {
        ...data,
        items: (data.nodes ?? []).map((node) => ({
          ...node,
          node_id: node.id,
          locality: node.site,
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
  });
}

export function useNodeStates() {
  return useQuery({
    queryKey: ["nodes", "states"],
    queryFn: api.nodes.states,
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useNodeCoverage() {
  return useQuery({
    queryKey: ["nodes", "coverage"],
    queryFn: api.nodes.coverage,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

/* ================================================================== */
/* Réseau                                                              */
/* ================================================================== */
export function useNetworkSnapshot() {
  return useQuery({
    queryKey: ["network", "snapshot"],
    queryFn: api.metrics.snapshot,
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useNodesDown() {
  return useQuery({
    queryKey: ["network", "down"],
    queryFn: api.metrics.down,
    refetchInterval: useInterval(REFRESH.LIVE),
  });
}

export function useTopNodes(options = 10) {
  // Les anciens écrans passent un objet ({ metricType, hours, limit }) :
  // transmis tel quel, il partait en `limit=[object Object]` et le backend
  // répondait 422.
  const limit = typeof options === "object" ? (options?.limit ?? 10) : options;
  return useQuery({
    queryKey: ["network", "top", limit],
    queryFn: () => api.metrics.top(limit),
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
  [168, "7d"],
  [720, "30d"],
  [2160, "90d"],
];

function periodFromHours(hours) {
  const match = SERIES_PERIODS.find(([limit]) => hours <= limit);
  return match ? match[1] : "1y";
}

/**
 * Courbe agrégée du réseau — même avertissement que ci-dessus.
 *
 * Rend une LISTE de points `{ time, value, min, max, nb_nodes }`, la forme
 * que lisent les écrans. Le backend renvoie un objet `{ points, … }` : le
 * passer tel quel faisait planter l'écran entier sur `.map`.
 *
 * `min` et `max` restent vides : la moyenne est calculée sur un échantillon
 * d'équipements et le backend ne publie pas le pire d'entre eux. Recopier la
 * moyenne dans « pire équipement » serait un mensonge graphique.
 */
export function useNetworkSeries({ metric, metricType, period, hours, sample } = {}) {
  const metricKey = metric ?? metricType ?? "latency_ms";
  const periodKey = period ?? (hours ? periodFromHours(hours) : "24h");
  return useQuery({
    queryKey: ["metrics", "network", metricKey, periodKey, sample],
    queryFn: () => api.metrics.networkSeries({ metric: metricKey, period: periodKey, sample }),
    select: (data) =>
      (data?.points ?? []).map((point) => ({
        time: point.at,
        value: point.value,
        min: null,
        max: null,
        nb_nodes: data.contributing_nodes,
      })),
    refetchInterval: false,
    staleTime: 60_000,
    retry: 1,
  });
}

/* ================================================================== */
/* Tendances — agrégats journaliers                                    */
/* ================================================================== */
export function useKpiTrend({ days = 30, site } = {}) {
  return useQuery({
    queryKey: ["kpi", "trend", days, site],
    queryFn: () => api.kpi.trend({ days, site }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useKpiMonthly(params) {
  const period = usePeriodParams();
  const query = { ...period, ...params };
  return useQuery({
    queryKey: ["kpi", "monthly", query],
    queryFn: () => api.kpi.monthly(query),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useKpiSites({ days = 30, limit = 20 } = {}) {
  return useQuery({
    queryKey: ["kpi", "sites", days, limit],
    queryFn: () => api.kpi.sites({ days, limit }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useKpiCauses({ days = 90 } = {}) {
  return useQuery({
    queryKey: ["kpi", "causes", days],
    queryFn: () => api.kpi.causes({ days }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useResolutionTimes({ days = 30 } = {}) {
  return useQuery({
    queryKey: ["kpi", "resolution", days],
    queryFn: () => api.kpi.resolutionTimes({ days }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/* ================================================================== */
/* Engagements de service                                              */
/* ================================================================== */
export function useSlaCompliance({ days = 30 } = {}) {
  return useQuery({
    queryKey: ["sla", "compliance", days],
    queryFn: () => api.sla.compliance({ days }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

export function useSlaBreaches({ days = 30 } = {}) {
  return useQuery({
    queryKey: ["sla", "breaches", days],
    queryFn: () => api.sla.breaches({ days }),
    refetchInterval: useInterval(REFRESH.ANALYTIC),
  });
}

/**
 * Alertes en cours qui vont manquer leur objectif.
 *
 * Rafraîchi au régime LIVE et non ANALYTIC : c'est le seul indicateur SLA
 * sur lequel on peut encore agir, il perd tout intérêt s'il a cinq minutes
 * de retard.
 */
export function useSlaAtRisk() {
  return useQuery({
    queryKey: ["sla", "at-risk"],
    queryFn: api.sla.atRisk,
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
  return useQuery({
    queryKey: ["interop", "status"],
    queryFn: api.interop.status,
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
    // Cet écran doit rester affichable quand tout le reste ne l'est plus :
    // on ne renonce pas au premier échec.
    retry: 3,
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
export function useMaintenanceWindows(options = "all") {
  // Les anciens écrans passent `{ onlyActive, limit }` au lieu d'une portée.
  const scope =
    typeof options === "object" ? (options?.onlyActive ? "active" : "all") : options;
  return useQuery({
    queryKey: ["maintenance", scope],
    queryFn: () => api.maintenance.list(scope),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useMaintenanceActions() {
  const queryClient = useQueryClient();
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["maintenance"] });
    // Une fenêtre change l'état affiché des équipements qu'elle couvre.
    queryClient.invalidateQueries({ queryKey: ["nodes"] });
    queryClient.invalidateQueries({ queryKey: ["alerts"] });
  };
  return {
    create: useMutation({ mutationFn: api.maintenance.create, onSuccess: invalidate }),
    remove: useMutation({ mutationFn: api.maintenance.remove, onSuccess: invalidate }),
  };
}

/* ================================================================== */
/* Terrain                                                             */
/* ================================================================== */
export function useFieldInterventions(params = {}) {
  return useQuery({
    queryKey: ["field", params],
    queryFn: () => api.field.list(params),
    refetchInterval: useInterval(REFRESH.OPERATIONAL),
  });
}

export function useFieldActions() {
  const queryClient = useQueryClient();
  const currentUserId = useAuthStore((s) => s.user?.id);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["field"] });
  return {
    // L'équipement est désigné par sa CLÉ (`netxms:464322`), plus par un
    // entier. Sans agent désigné, l'intervention revient à qui la programme :
    // l'écran Terrain n'a pas de sélecteur d'agent.
    create: useMutation({
      mutationFn: ({ node_id: nodeId, node_key: nodeKey, incident_id: incidentId, alert_key: alertKey, agent_user_id: agentId, scheduled_at: scheduledAt }) =>
        api.field.create({
          node_key: nodeKey ?? nodeId,
          alert_key: alertKey ?? incidentId ?? null,
          agent_user_id: agentId ?? currentUserId,
          scheduled_at: scheduledAt ?? null,
        }),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ id, payload }) => api.field.update(id, payload),
      onSuccess: invalidate,
    }),
    updateStatus: useMutation({
      mutationFn: ({ id, status }) => api.field.update(id, { status }),
      onSuccess: invalidate,
    }),
    // Le compte rendu CLÔTURE l'intervention : la route n'a qu'un point
    // d'entrée, le changement de statut, qui porte aussi texte et position.
    submitReport: useMutation({
      mutationFn: ({ id, payload }) =>
        api.field.update(id, {
          status: "done",
          report_text: payload.report_text,
          latitude: payload.checkin_latitude ?? null,
          longitude: payload.checkin_longitude ?? null,
        }),
      onSuccess: invalidate,
    }),
  };
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
    description: alert.message,
    locality: alert.site,
    node_id: alert.node_key,
    source_tool: alert.tool,
    external_id: alert.ref,
    assigned_to_full_name: alert.assigned_to,
    cause_label: alert.cause,
    itop_ticket_ref: alert.ticket_ref,
  };
}

/** Ancien résumé d'alertes, dérivé de l'instantané. */
export function useAlertSummary() {
  const overview = useOverview();
  const states = useNodeStates();
  const data = overview.data;
  const nodeStates = states.data;

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
          up: nodeStates?.up ?? 0,
          down: nodeStates?.down ?? 0,
          degraded: nodeStates?.degraded ?? 0,
          silent: nodeStates?.silent ?? 0,
          maintenance: nodeStates?.maintenance ?? 0,
          localities_affected: data.sites_impacted ?? 0,
          // L'ancienneté de la plus vieille alerte non acquittée n'est plus
          // calculée côté serveur : la liste d'alertes est déjà triée par
          // gravité puis par date, l'écran la lit sur sa dernière ligne.
          oldest_unacknowledged_at: null,
          snapshot_age_s: data.snapshot_age_s,
          stale: data.stale,
        }
      : undefined,
  };
}

/** Alertes ouvertes, en liste plate comme l'attendaient les anciens écrans. */
export function useOpenAlerts({ limit = 50 } = {}) {
  const query = useAlerts({ limit, acknowledged: false });
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
          availability_pct: data.fleet_health_pct,
          // « Remontent » = les équipements dont un outil dit quelque chose.
          // Les muets sont précisément ceux qui ne remontent plus rien.
          nodes_reporting: (data.nodes_total ?? 0) - (data.nodes_silent ?? 0),
          // Seule la disponibilité se déduit de l'instantané ; latence,
          // pertes, CPU se lisent chez les outils sources, sur demande. Les
          // tuiles correspondantes disent donc « non collectée ».
          metric_types_available: data.fleet_health_pct != null ? ["availability_pct"] : [],
        }
      : undefined,
  };
}

/** Incidents, devenus alertes — voir l'en-tête de api/noc.js. */
export function useIncidents(params = {}) {
  const query = useAlerts(params);
  return {
    ...query,
    data: query.data
      ? { items: query.data.alerts.map(toIncident), total: query.data.total }
      : undefined,
  };
}

export function useIncident(alertKey) {
  const query = useAlert(alertKey);
  return { ...query, data: query.data ? toIncident(query.data) : undefined };
}

/**
 * Enveloppe une mutation pour traduire les arguments d'un ancien écran vers
 * la signature native. Le reste de l'objet (isPending, error…) est conservé.
 */
function translated(mutation, translate) {
  return {
    ...mutation,
    mutate: (argument, options) => mutation.mutate(translate(argument), options),
    mutateAsync: (argument, options) => mutation.mutateAsync(translate(argument), options),
  };
}

/**
 * Actions sur incident, sous les anciens noms ET avec les anciens arguments.
 *
 * La fiche d'incident appelle `acknowledge(id)`, `resolve({ id, notes })`,
 * `assign({ id, userId, note })`… alors que les actions natives attendent
 * `{ alertKey, … }`. Sans cette traduction, chaque bouton de la fiche
 * enverrait une requête vers /alerts/undefined.
 */
export function useIncidentActions() {
  const actions = useAlertActions();
  const keyOf = (argument) =>
    typeof argument === "object" ? (argument.alertKey ?? argument.id) : argument;

  return {
    ...actions,
    acknowledge: translated(actions.acknowledge, (argument) => ({
      alertKey: keyOf(argument),
      note: typeof argument === "object" ? argument.note : undefined,
    })),
    resolve: translated(actions.resolve, (argument) => ({
      alertKey: keyOf(argument),
      cause: argument.cause ?? null,
      note: argument.note ?? argument.notes ?? null,
    })),
    assign: translated(actions.assign, (argument) => ({
      alertKey: keyOf(argument),
      assigneeId: argument.assigneeId ?? argument.userId,
      note: argument.note ?? null,
    })),
    // L'escalade n'est plus une action distincte : elle se traduit par une
    // affectation à quelqu'un d'autre, avec le motif en consigne.
    escalate: translated(actions.assign, (argument) => ({
      alertKey: keyOf(argument),
      assigneeId: argument.assigneeId ?? argument.userId,
      note: argument.reason ?? argument.note ?? null,
    })),
    comment: translated(actions.addNote, (argument) => ({
      alertKey: keyOf(argument),
      note: argument.note,
    })),
  };
}

export function useCoverage() {
  return useNodeCoverage();
}

export function useCoverageTrend({ days = 30 } = {}) {
  return useKpiTrend({ days });
}

export function useKpiSummary(params) {
  return useKpiMonthly(params);
}

/**
 * Localités, devenues sites. Accepte l'ancien appel `useKpiLocalities(8)`, et
 * rend chaque site sous les anciens noms de champs. Ce que les agrégats
 * journaliers ne portent pas (MTTR, région) reste vide.
 */
export function useKpiLocalities(params = {}) {
  const query = useKpiSites(typeof params === "number" ? { limit: params } : params);
  return {
    ...query,
    data: query.data?.map((row) => ({
      ...row,
      locality: row.site,
      locality_id: row.site,
      region: null,
      total_incidents: row.avg_alerts,
      critical: row.avg_critical ?? null,
      avg_mttr: null,
    })),
  };
}

/**
 * Carte des localités — VOLONTAIREMENT VIDE.
 *
 * Le NOC ne tient plus de coordonnées géographiques : elles vivaient dans
 * `dim_locality`, supprimée avec l'entrepôt, et aucun outil source ne les
 * publie. La carte doit être réalimentée par une source explicite — un
 * fichier de référence, ou un champ ajouté aux Location d'iTop. Rendre une
 * liste vide fait apparaître une carte sans points, ce qui est le signal
 * correct ; poser des points au jugé sur le Burkina serait pire.
 */
export function useKpiLocalitiesMap() {
  return { data: [], isLoading: false, isError: false, error: null };
}

/**
 * Ministères — VOLONTAIREMENT VIDE.
 *
 * Concept de l'entrepôt supprimé. L'équivalent est `organisation`, porté
 * par les CI d'iTop et déjà lisible sur chaque équipement ; il manque
 * seulement un agrégat par organisation côté backend.
 */
export function useKpiMinistries() {
  return { data: [], isLoading: false, isError: false, error: null };
}

/** Équipements récurrents, devenus les plus alertants de l'instantané. */
export function useKpiRecurrent({ limit = 10 } = {}) {
  return useTopNodes(limit);
}

export function useKpiHourDistribution() {
  return useHourDistribution();
}

export function useLocalityNodes(site) {
  return useNodes(site ? { site } : {});
}

/** Alertes actives d'un équipement — déjà portées par sa fiche. */
export function useNodeIncidents(nodeId) {
  const query = useNode(nodeId);
  return { ...query, data: query.data?.active_alerts ?? [] };
}

/**
 * Dernière valeur de chaque métrique d'un équipement.
 *
 * Interroge l'outil source, et rend la dernière valeur de la série sur une
 * heure : il n'y a plus de table de « dernières valeurs » côté NOC,
 * puisqu'aucune métrique n'y est recopiée.
 */
export function useNodeLatest(nodeId) {
  const query = useNodeSeries(nodeId, { period: "1h" });
  const series = query.data?.series;
  return {
    ...query,
    data: series
      ? Object.fromEntries(
          Object.entries(series).map(([metric, value]) => [
            metric,
            value.points?.length ? value.points[value.points.length - 1] : null,
          ]),
        )
      : undefined,
  };
}

/**
 * Engagements de service, sous la forme de l'ancien écran SLA.
 *
 * Le backend rend, par gravité, les délais moyens et si l'objectif est tenu
 * EN MOYENNE ; les dépassements individuels viennent de /sla/breaches. Les
 * taux de conformité sont recalculés ici à partir de ces deux sources. Les
 * « indicateurs de service » réseau (latence, disponibilité contractuelle)
 * n'ont plus de source : la liste est vide plutôt qu'inventée.
 */
export function useSla(params = {}) {
  const compliance = useSlaCompliance(params);
  const breaches = useSlaBreaches(params);
  const data = compliance.data;
  const breachList = Array.isArray(breaches.data) ? breaches.data : [];

  const breachedBySeverity = {};
  for (const breach of breachList) {
    breachedBySeverity[breach.severity] = (breachedBySeverity[breach.severity] ?? 0) + 1;
  }
  const handled = data?.handled_total ?? 0;
  const totalBreached = breachList.length;

  return {
    ...compliance,
    data: data
      ? {
          ...data,
          global_compliance_pct: handled
            ? Math.max(0, ((handled - totalBreached) / handled) * 100)
            : null,
          total_breached: totalBreached,
          indicators: [],
          by_severity: (data.by_severity ?? []).map((row) => {
            const breached = breachedBySeverity[row.severity] ?? 0;
            return {
              ...row,
              total_incidents: row.alerts,
              avg_mtta_minutes: row.mtta_minutes,
              avg_mttr_minutes: row.mttr_minutes,
              breached,
              ttr_compliance_pct: row.alerts
                ? Math.max(0, ((row.alerts - breached) / row.alerts) * 100)
                : null,
            };
          }),
        }
      : undefined,
  };
}

/**
 * Charge par opérateur.
 *
 * Reconstituée depuis les alertes affectées : le backend ne tient plus
 * d'agrégat dédié, et le calcul est trivial sur une liste déjà chargée par
 * l'écran.
 */
export function useWorkload() {
  const query = useAlerts({ limit: 1000 });
  const rows = query.data?.alerts ?? [];
  const now = Date.now();
  const byAssignee = new Map();
  for (const alert of rows) {
    if (alert.resolved_at) continue;
    // `assigned_to` porte le NOM de l'intervenant (alerts_service) : il sert
    // de clé. `user_id: null` désigne la ligne « non affecté », que l'écran
    // met en tête et en couleur d'alerte.
    const who = alert.assigned_to ?? null;
    const entry = byAssignee.get(who) ?? {
      user_id: who,
      full_name: who ?? "Non affecté",
      role: null,
      open_incidents: 0,
      critical: 0,
      unacknowledged: 0,
      oldest_age_minutes: 0,
    };
    entry.open_incidents += 1;
    if (alert.severity === "critical") entry.critical += 1;
    if (!alert.acknowledged) entry.unacknowledged += 1;
    const since = alert.since ? Date.parse(alert.since) : NaN;
    if (!Number.isNaN(since)) {
      entry.oldest_age_minutes = Math.max(entry.oldest_age_minutes, (now - since) / 60_000);
    }
    byAssignee.set(who, entry);
  }
  return {
    ...query,
    data: [...byAssignee.values()].sort(
      (a, b) => (a.user_id === null ? -1 : b.user_id === null ? 1 : b.open_incidents - a.open_incidents),
    ),
  };
}

/**
 * Ancien référentiel géographique.
 *
 * Régions et ministères n'existent plus : ils vivaient dans l'entrepôt
 * supprimé. Le seul axe de regroupement qui subsiste est le SITE, tel que
 * les outils sources le déclarent. Les listes vides sont délibérées — elles
 * font apparaître des sélecteurs sans options, signal correct que ces
 * filtres doivent être remplacés par un filtre sur le site.
 */
export function useReference() {
  const sites = useSites();
  return {
    ...sites,
    data: {
      sites: sites.data ?? [],
      localities: (sites.data ?? []).map((entry) => ({
        id: entry.site,
        name: entry.site,
        region_id: null,
      })),
      regions: [],
      ministries: [],
    },
  };
}

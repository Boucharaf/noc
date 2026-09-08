/**
 * Contrat d'API — miroir exact des routes du backend.
 *
 * Tout regroupé dans UN fichier, et pas un module par domaine : c'est le
 * document de référence qui doit rester aligné avec `backend/app/routes/`.
 * Éclaté en quinze fichiers de six lignes, la dérive entre les deux côtés
 * passe inaperçue ; ici un `git diff` sur les routes backend se compare
 * ligne à ligne avec celui-ci.
 *
 * Aucune fonction ne fait de traitement : elles renvoient `data` brut. La
 * mise en forme vit dans `lib/format.js`, le cache et le polling dans
 * `hooks/queries.js`.
 */
import apiClient from "./client";

const get = (url, params) => apiClient.get(url, { params }).then((r) => r.data);
const post = (url, body) => apiClient.post(url, body).then((r) => r.data);
const patch = (url, body) => apiClient.patch(url, body).then((r) => r.data);
const del = (url, config) => apiClient.delete(url, config).then((r) => r.data);

/* ------------------------------------------------------------------ */
/* Authentification et comptes                                         */
/* ------------------------------------------------------------------ */
export const auth = {
  login: (username, password) => post("/auth/login", { username, password }),
  pinLogin: (pin) => post("/auth/pin-login", { pin }),
  logout: () => post("/auth/logout"),
  me: () => get("/auth/me"),
  changePassword: (current_password, new_password) =>
    patch("/auth/me/password", { current_password, new_password }),
  revokeSessions: (userId) => post(`/auth/users/${userId}/revoke-sessions`),
};

export const users = {
  list: () => get("/users"),
  create: (payload) => post("/users", payload),
  update: (userId, payload) => patch(`/users/${userId}`, payload),
  deactivate: (userId) => post(`/users/${userId}/deactivate`),
  resetPin: (userId, new_pin) => post(`/users/${userId}/reset-pin`, { new_pin }),
};

/* ------------------------------------------------------------------ */
/* Référentiel                                                          */
/* ------------------------------------------------------------------ */
export const geo = {
  reference: () => get("/geo/reference"),
  regions: () => get("/geo/regions"),
  localities: (region_id) => get("/geo/localities", { region_id }),
  ministries: () => get("/geo/ministries"),
};

/* ------------------------------------------------------------------ */
/* KPI mensuels — tous acceptent { month, year }                        */
/* ------------------------------------------------------------------ */
export const kpi = {
  summary: (params) => get("/kpi/summary", params),
  localities: (params) => get("/kpi/localities", params),
  localitiesMap: (params) => get("/kpi/localities/map", params),
  nodes: (params) => get("/kpi/nodes", params),
  recurrent: (params) => get("/kpi/recurrent", params),
  trend: (params) => get("/kpi/trend", params),
  hourDistribution: (params) => get("/kpi/hour-distribution", params),
  causes: (params) => get("/kpi/causes", params),
  compare: (params) => get("/kpi/compare", params),
  ministries: (params) => get("/kpi/ministries", params),
  localityNodes: (localityId, params) => get(`/locality/${localityId}/nodes`, params),
};

/* ------------------------------------------------------------------ */
/* Alertes — l'état « maintenant », par opposition aux KPI mensuels     */
/* ------------------------------------------------------------------ */
export const alerts = {
  open: (params) => get("/alerts/open", params),
  recent: (params) => get("/alerts/recent", params),
  counts: () => get("/alerts/counts"),
  summary: (params) => get("/alerts/summary", params),
};

/* ------------------------------------------------------------------ */
/* Incidents                                                            */
/* ------------------------------------------------------------------ */
export const incidents = {
  list: (params) => get("/incidents", params),
  detail: (id) => get(`/incidents/${id}`),
  timeline: (id) => get(`/incidents/${id}/timeline`),
  workload: () => get("/incidents/workload"),
  acknowledge: (id) => patch(`/incidents/${id}/acknowledge`),
  resolve: (id, notes) => patch(`/incidents/${id}/resolve`, { notes }),
  assign: (id, assigned_to_user_id, note) =>
    post(`/incidents/${id}/assign`, { assigned_to_user_id, note }),
  escalate: (id, escalated_to_user_id, reason) =>
    post(`/incidents/${id}/escalate`, { escalated_to_user_id, reason }),
  comment: (id, note) => post(`/incidents/${id}/comment`, { note }),
  createManual: (payload) => post("/incidents/manual", payload),
  // Renvoie un Blob : le navigateur doit déclencher un téléchargement,
  // pas afficher du CSV dans la console.
  exportCsv: (params) =>
    apiClient
      .get("/incidents/export.csv", { params, responseType: "blob" })
      .then((r) => r.data),
};

/* ------------------------------------------------------------------ */
/* Équipements (inventaire, niveau 4 de l'architecture métier)          */
/* ------------------------------------------------------------------ */
export const nodes = {
  list: (params) => get("/nodes", params),
  states: (params) => get("/nodes/states", params),
  detail: (nodeId) => get(`/nodes/${nodeId}`),
  incidents: (nodeId, params) => get(`/nodes/${nodeId}/incidents`, params),
};

/* ------------------------------------------------------------------ */
/* Métriques TimescaleDB                                                */
/* ------------------------------------------------------------------ */
export const metrics = {
  network: (params) => get("/metrics/network", params),
  networkSeries: (params) => get("/metrics/network/series", params),
  top: (params) => get("/metrics/top", params),
  nodesDown: (params) => get("/metrics/nodes/down", params),
  nodeSeries: (nodeId, params) => get(`/metrics/nodes/${nodeId}/series`, params),
  nodeLatest: (nodeId) => get(`/metrics/nodes/${nodeId}/latest`),
};

/* ------------------------------------------------------------------ */
/* SLA, couverture, interopérabilité                                    */
/* ------------------------------------------------------------------ */
export const sla = {
  get: (params) => get("/sla", params),
  targets: () => get("/sla/targets"),
  updateTarget: (severity, payload) => patch(`/sla/targets/${severity}`, payload),
};

export const coverage = {
  // Le préfixe reste /api/assets côté backend bien que dim_asset ait
  // disparu : la donnée vient de fact_supervision_coverage_daily.
  summary: () => get("/assets/coverage"),
  trend: (params) => get("/assets/coverage/trend", params),
};

export const interop = {
  status: (params) => get("/interop/status", params),
};

export const health = {
  check: () => get("/health"),
};

/* ------------------------------------------------------------------ */
/* Maintenance planifiée                                                */
/* ------------------------------------------------------------------ */
export const maintenance = {
  list: (params) => get("/maintenance-windows", params),
  create: (payload) => post("/maintenance-windows", payload),
  remove: (windowId) => del(`/maintenance-windows/${windowId}`),
};

/* ------------------------------------------------------------------ */
/* Interventions terrain                                                */
/* ------------------------------------------------------------------ */
export const field = {
  list: (params) => get("/field-interventions", params),
  create: (payload) => post("/field-interventions", payload),
  updateStatus: (id, status) => patch(`/field-interventions/${id}/status`, { status }),
  submitReport: (id, payload) => post(`/field-interventions/${id}/report`, payload),
};

/* ------------------------------------------------------------------ */
/* Rapports et notifications                                            */
/* ------------------------------------------------------------------ */
export const report = {
  monthly: (params) =>
    apiClient
      .get("/report/monthly", { params, responseType: "blob" })
      .then((r) => r.data),
};

export const notifications = {
  vapidKey: () => get("/notifications/vapid-public-key"),
  subscribe: (payload) => post("/notifications/subscribe", payload),
  unsubscribe: (endpoint) => del("/notifications/subscribe", { data: { endpoint } }),
};

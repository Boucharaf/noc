import apiClient from "./client";

// Chaque fonction accepte désormais un `signal` optionnel (AbortSignal).
// TanStack Query le fournit automatiquement à queryFn — le propager jusqu'à
// axios permet d'annuler une requête KPI abandonnée (ex. changement rapide
// de mois/localité sur le dashboard) au lieu de laisser des réponses
// obsolètes arriver en retard et écraser un état plus récent (race condition
// classique sur les dashboards à filtres).

export const getSummary = (month, year, signal) =>
  apiClient.get("/kpi/summary", { params: { month, year }, signal }).then((r) => r.data);

export const getLocalities = (month, year, limit = 10, signal) =>
  apiClient
    .get("/kpi/localities", { params: { month, year, limit }, signal })
    .then((r) => r.data);

export const getNodes = (month, year, localityId, limit = 10, signal) =>
  apiClient
    .get("/kpi/nodes", {
      params: { month, year, locality_id: localityId, limit },
      signal,
    })
    .then((r) => r.data);

export const getRecurrent = (month, year, minCount = 3, signal) =>
  apiClient
    .get("/kpi/recurrent", { params: { month, year, min_count: minCount }, signal })
    .then((r) => r.data);

export const getTrend = (month, year, months = 6, signal) =>
  apiClient
    .get("/kpi/trend", { params: { month, year, months }, signal })
    .then((r) => r.data);

export const getHourDistribution = (month, year, signal) =>
  apiClient
    .get("/kpi/hour-distribution", { params: { month, year }, signal })
    .then((r) => r.data);

export const getLocalityNodes = (localityId, month, year, signal) =>
  apiClient
    .get(`/locality/${localityId}/nodes`, { params: { month, year }, signal })
    .then((r) => r.data);

export const getCauses = (month, year, signal) =>
  apiClient.get("/kpi/causes", { params: { month, year }, signal }).then((r) => r.data);

export const getLocalitiesMap = (month, year, signal) =>
  apiClient
    .get("/kpi/localities/map", { params: { month, year }, signal })
    .then((r) => r.data);

export const getCompare = (month, year, signal) =>
  apiClient
    .get("/kpi/compare", { params: { month, year }, signal })
    .then((r) => r.data);
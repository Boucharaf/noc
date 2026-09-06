import apiClient from "./client";

// KPI réseau agrégés (disponibilité, perte de paquets, latence, bande
// passante) sur les `hours` dernières heures — voir app/routes/metrics.py.
export const getNetworkKpi = (hours = 24, signal) =>
  apiClient.get("/metrics/network", { params: { hours }, signal }).then((r) => r.data);

export const getNodesDown = (signal) =>
  apiClient.get("/metrics/nodes/down", { signal }).then((r) => r.data);

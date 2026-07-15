import apiClient from "./client";

export const getOpenAlerts = (limit = 20) =>
  apiClient.get("/alerts/open", { params: { limit } }).then((r) => r.data);

export const getRecentNotifications = (limit = 10) =>
  apiClient.get("/alerts/recent", { params: { limit } }).then((r) => r.data);

export const acknowledgeIncident = (id) =>
  apiClient.patch(`/incidents/${id}/acknowledge`, {}).then((r) => r.data);

export const resolveIncident = (id, notes) =>
  apiClient.patch(`/incidents/${id}/resolve`, { notes }).then((r) => r.data);

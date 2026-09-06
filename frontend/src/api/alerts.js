import apiClient from "./client";
import { useAuthStore } from "../store/auth";
import { assertPermission, PERMISSIONS } from "./permissions";

function currentRole() {
  return useAuthStore.getState().user?.role;
}

export const getOpenAlerts = (limit = 20, localityId = null, signal) =>
  apiClient
    .get("/alerts/open", {
      params: { limit, ...(localityId ? { locality_id: localityId } : {}) },
      signal, // permet l'annulation propre (TanStack Query passe déjà ce signal)
    })
    .then((r) => r.data);

export const getRecentNotifications = (limit = 10, signal) =>
  apiClient.get("/alerts/recent", { params: { limit }, signal }).then((r) => r.data);

// Historique paginé/filtrable — GET /api/incidents (voir
// app/routes/incidents.py::list_incidents). Distinct de getOpenAlerts : celui-ci
// couvre aussi les incidents résolus/clôturés, sur toute période.
export const listIncidents = (filters = {}, signal) => {
  const { status, severity, localityId, nodeCode, sourceTool, dateFrom, dateTo, page = 1, pageSize = 25 } = filters;
  return apiClient
    .get("/incidents", {
      params: {
        status,
        severity,
        locality_id: localityId,
        node_code: nodeCode,
        source_tool: sourceTool,
        date_from: dateFrom,
        date_to: dateTo,
        page,
        page_size: pageSize,
      },
      signal,
    })
    .then((r) => r.data);
};

// Signalement manuel — POST /api/incidents/manual. Réservé aux terrains/techniques
// (voir _MANUAL_INCIDENT_ROLES côté backend) : un problème constaté sur site
// que les outils de supervision n'ont pas détecté (câble coupé, groupe
// électrogène en panne...).
export const createManualIncident = ({ nodeCode, severity, description, causeCategory, causeLabel }) => {
  assertPermission(currentRole(), PERMISSIONS.CREATE_MANUAL_INCIDENT);
  return apiClient
    .post("/incidents/manual", {
      node_code: nodeCode,
      severity,
      description,
      cause_category: causeCategory ?? null,
      cause_label: causeLabel ?? null,
    })
    .then((r) => r.data);
};

export const acknowledgeIncident = (id) => {
  assertPermission(currentRole(), PERMISSIONS.ACKNOWLEDGE_INCIDENT);
  return apiClient.patch(`/incidents/${id}/acknowledge`, {}).then((r) => r.data);
};

export const resolveIncident = (id, notes) => {
  assertPermission(currentRole(), PERMISSIONS.RESOLVE_INCIDENT);
  const trimmed = (notes ?? "").trim();
  if (!trimmed) {
    // Une résolution sans note est une perte d'information pour le post-mortem
    // et pour l'audit — on bloque côté client avant même l'appel réseau.
    throw new Error("Une note de résolution est obligatoire pour clôturer un incident.");
  }
  return apiClient
    .patch(`/incidents/${id}/resolve`, { notes: trimmed })
    .then((r) => r.data);
};

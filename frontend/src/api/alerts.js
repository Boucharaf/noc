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

// Détail d'un incident — manquant du fichier d'origine ; nécessaire dès
// qu'on ouvre un panneau de détail depuis IncidentTable plutôt que de tout
// afficher en liste (contexte, historique de statut, CI lié iTop, etc.).
export const getIncidentDetail = (id, signal) =>
  apiClient.get(`/incidents/${id}`, { signal }).then((r) => r.data);

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

// Acquittement en masse pour un Chef NOC/Technicien pendant une panne
// multi-sites (ex. coupure électrique régionale générant 30 alertes) —
// évite 30 clics identiques pendant un incident majeur.
export const bulkAcknowledgeIncidents = (ids = []) => {
  assertPermission(currentRole(), PERMISSIONS.BULK_ACKNOWLEDGE);
  if (!Array.isArray(ids) || ids.length === 0) {
    throw new Error("Aucun incident sélectionné.");
  }
  return apiClient
    .post("/incidents/bulk-acknowledge", { incident_ids: ids })
    .then((r) => r.data);
};
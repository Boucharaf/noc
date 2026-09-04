import apiClient from "./client";

// Toutes ces routes sont réservées côté backend au rôle agent_terrain
// (voir app/routes/field.py) et ne renvoient que les tournées de l'agent
// connecté — pas de paramètre user_id ici, le backend le déduit du JWT.

export const getMyInterventions = (status = null, signal) =>
  apiClient
    .get("/field-interventions", { params: status ? { status } : {}, signal })
    .then((r) => r.data);

export const createIntervention = ({ nodeId, incidentId = null, scheduledAt = null }) =>
  apiClient
    .post("/field-interventions", {
      node_id: nodeId,
      incident_id: incidentId,
      scheduled_at: scheduledAt,
    })
    .then((r) => r.data);

export const updateInterventionStatus = (interventionId, status) =>
  apiClient
    .patch(`/field-interventions/${interventionId}/status`, { status })
    .then((r) => r.data);

export const submitInterventionReport = (
  interventionId,
  { reportText, checkinLatitude = null, checkinLongitude = null, photoUrls = [] }
) =>
  apiClient
    .post(`/field-interventions/${interventionId}/report`, {
      report_text: reportText,
      checkin_latitude: checkinLatitude,
      checkin_longitude: checkinLongitude,
      photo_urls: photoUrls,
    })
    .then((r) => r.data);

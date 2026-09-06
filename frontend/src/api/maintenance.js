import apiClient from "./client";
import { useAuthStore } from "../store/auth";
import { assertPermission, PERMISSIONS } from "./permissions";

export const getMaintenanceWindows = (signal) =>
  apiClient.get("/maintenance-windows", { signal }).then((r) => r.data);

export const createMaintenanceWindow = ({ nodeId = null, localityId = null, reason, startsAt, endsAt, suppressAlerts = true }) => {
  assertPermission(useAuthStore.getState().user?.role, PERMISSIONS.CREATE_MAINTENANCE_WINDOW);
  return apiClient
    .post("/maintenance-windows", {
      node_id: nodeId,
      locality_id: localityId,
      reason,
      starts_at: startsAt,
      ends_at: endsAt,
      suppress_alerts: suppressAlerts,
    })
    .then((r) => r.data);
};

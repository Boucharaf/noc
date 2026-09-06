import apiClient from "./client";
import { useAuthStore } from "../store/auth";
import { assertPermission, PERMISSIONS } from "./permissions";

function guard() {
  assertPermission(useAuthStore.getState().user?.role, PERMISSIONS.MANAGE_USERS);
}

export const listUsers = (signal) =>
  apiClient.get("/users", { signal }).then((r) => r.data);

export const createUser = (payload) => {
  guard();
  return apiClient
    .post("/users", {
      username: payload.username,
      full_name: payload.fullName,
      role: payload.role,
      password: payload.password,
      pin: payload.pin || null,
      phone_number: payload.phoneNumber || null,
      region_id: payload.regionId ?? null,
      locality_id: payload.localityId ?? null,
      employee_code: payload.employeeCode || null,
      team: payload.team || null,
    })
    .then((r) => r.data);
};

export const updateUser = (userId, payload) => {
  guard();
  return apiClient.patch(`/users/${userId}`, payload).then((r) => r.data);
};

export const deactivateUser = (userId) => {
  guard();
  return apiClient.post(`/users/${userId}/deactivate`, {}).then((r) => r.data);
};

export const resetUserPin = (userId, newPin) => {
  guard();
  return apiClient.post(`/users/${userId}/reset-pin`, { new_pin: newPin }).then((r) => r.data);
};

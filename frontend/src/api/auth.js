import apiClient from "./client";

export const loginWithPassword = (username, password) =>
  apiClient.post("/auth/login", { username, password }).then((r) => r.data);

export const loginWithPin = (pin) =>
  apiClient.post("/auth/pin-login", { pin }).then((r) => r.data);

export const refreshSession = () =>
  apiClient.post("/auth/refresh").then((r) => r.data);

export const getMe = () => apiClient.get("/auth/me").then((r) => r.data);

import apiClient from "./client";

export const getInteropStatus = (month, year, signal) =>
  apiClient
    .get("/interop/status", { params: { month, year }, signal })
    .then((r) => r.data);
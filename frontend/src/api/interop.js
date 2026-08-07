import apiClient from "./client";

export const getInteropStatus = (month, year) =>
  apiClient
    .get("/interop/status", { params: { month, year } })
    .then((r) => r.data);

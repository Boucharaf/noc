import apiClient from "./client";

export const getSLA = (month, year, signal) =>
  apiClient.get("/sla", { params: { month, year }, signal }).then((r) => r.data);
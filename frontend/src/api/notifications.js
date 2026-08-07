import apiClient from "./client";

export const getVapidPublicKey = () =>
  apiClient.get("/notifications/vapid-public-key").then((r) => r.data.public_key);

// Both subscribe and unsubscribe answer 204 with no body, so neither unwraps
// a response — callers await them for success or failure only.
export const subscribePush = (subscription) =>
  apiClient.post("/notifications/subscribe", subscription);

export const unsubscribePush = (endpoint) =>
  apiClient.delete("/notifications/subscribe", { data: { endpoint } });

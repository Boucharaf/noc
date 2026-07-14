import apiClient from "./client";

export const getVapidPublicKey = () =>
  apiClient.get("/notifications/vapid-public-key").then((r) => r.data.public_key);

export const subscribePush = (subscription) =>
  apiClient.post("/notifications/subscribe", subscription).then((r) => r.data);

export const unsubscribePush = (endpoint) =>
  apiClient
    .delete("/notifications/subscribe", { data: { endpoint, keys: { p256dh: "", auth: "" } } })
    .then((r) => r.data);

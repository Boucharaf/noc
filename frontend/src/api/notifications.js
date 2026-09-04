import apiClient from "./client";

export const getVapidPublicKey = () =>
  apiClient.get("/notifications/vapid-public-key").then((r) => r.data.public_key);

// Both subscribe and unsubscribe answer 204 with no body, so neither unwraps
// a response — callers await them for success or failure only.
export const subscribePush = (subscription) =>
  apiClient.post("/notifications/subscribe", subscription);

export const unsubscribePush = (endpoint) =>
  apiClient.delete("/notifications/subscribe", { data: { endpoint } });

/* 
import apiClient from "./client";

export const getVapidPublicKey = () =>
  apiClient.get("/notifications/vapid-public-key").then((r) => r.data.public_key);

// Both subscribe and unsubscribe answer 204 with no body, so neither unwraps
// a response — callers await them for success or failure only.
export const subscribePush = (subscription) =>
  apiClient.post("/notifications/subscribe", subscription);

export const unsubscribePush = (endpoint) =>
  apiClient.delete("/notifications/subscribe", { data: { endpoint } });

// Utilitaire pour désabonner proprement au logout ou à la désactivation des
// notifications dans les préférences — évite d'accumuler des endpoints morts
// côté backend (push_subscription) au fil des changements d'appareil.
export const unsubscribeCurrentDevice = async () => {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (!subscription) return;
  await unsubscribePush(subscription.endpoint);
  await subscription.unsubscribe();
};*/
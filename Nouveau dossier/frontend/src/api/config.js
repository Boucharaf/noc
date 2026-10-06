// Module sans dépendance : importable à la fois par api/client.js et
// store/auth.js sans créer de cycle (client → store → client).
export const BASE_URL = import.meta.env.VITE_API_URL || "/api";

// URL du flux WebSocket temps réel. Déduite de l'origine courante plutôt
// que codée en dur : en développement Vite proxifie /ws vers le backend,
// en production nginx fait la même chose sur le même hôte. Une variable
// séparée resterait à maintenir alors qu'elle vaut toujours la même chose.
export function realtimeUrl() {
  const explicit = import.meta.env.VITE_WS_URL;
  if (explicit) return explicit;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/alerts`;
}

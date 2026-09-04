// api/config.js
// Module sans dépendance, importable à la fois par api/client.js et
// store/auth.js sans créer de cycle (client.js -> store/auth.js -> api/client.js).
export const BASE_URL = import.meta.env.VITE_API_URL || "/api";
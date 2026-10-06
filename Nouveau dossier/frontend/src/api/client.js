import axios from "axios";

import { BASE_URL } from "./config";
import { useAuthStore } from "../store/auth";

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 20000,
  // Le refresh token circule en cookie httpOnly : sans ce drapeau, le
  // navigateur ne le joindrait pas à /auth/refresh et toute session
  // expirerait au bout de la durée du jeton d'accès (30 min).
  withCredentials: true,
});

function requestId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

apiClient.interceptors.request.use((config) => {
  const { token } = useAuthStore.getState();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // Corrélation frontend ↔ journaux backend lors d'une investigation.
  config.headers["X-Request-Id"] = requestId();
  return config;
});

// Un dashboard NOC lance 10 à 15 requêtes au montage. Si le jeton vient
// d'expirer, elles échouent toutes en 401 en même temps : sans
// sérialisation, chacune déclencherait son propre /auth/refresh, et la
// rotation du refresh token en invaliderait toutes sauf une — ce qui
// déconnecterait l'utilisateur alors que sa session est valide.
let refreshPromise = null;

const isAuthEndpoint = (url = "") => url.includes("/auth/");

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    if (!response) {
      // Coupure réseau, timeout, CORS : à distinguer d'une erreur
      // applicative, l'interface affiche « backend injoignable » et non
      // « erreur ».
      return Promise.reject(Object.assign(error, { isNetworkError: true }));
    }

    if (response.status === 401 && !isAuthEndpoint(config?.url) && !config._retried) {
      config._retried = true;
      try {
        if (!refreshPromise) {
          refreshPromise = useAuthStore
            .getState()
            .refresh()
            .finally(() => {
              refreshPromise = null;
            });
        }
        const token = await refreshPromise;
        config.headers.Authorization = `Bearer ${token}`;
        return apiClient(config);
      } catch (refreshError) {
        // store.refresh() a déjà appelé logout("expired").
        return Promise.reject(refreshError);
      }
    }

    // 403 : session valide, rôle insuffisant. Surtout ne pas déconnecter —
    // c'est le cas normal quand un agent terrain atteint un écran réservé.
    if (response.status === 403) {
      return Promise.reject(Object.assign(error, { isForbidden: true }));
    }

    return Promise.reject(error);
  },
);

/** Message lisible pour l'utilisateur à partir d'une erreur axios. */
export function errorMessage(error, fallback = "Une erreur est survenue.") {
  if (!error) return fallback;
  if (error.isNetworkError) return "Backend injoignable. Vérifiez la connexion.";
  const detail = error.response?.data?.detail;
  if (typeof detail === "string") return detail;
  // Erreur de validation FastAPI : liste d'objets {loc, msg}.
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d.msg).join(" · ");
  }
  return error.message || fallback;
}

export default apiClient;

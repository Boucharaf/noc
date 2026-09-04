import axios from "axios";
import { useAuthStore } from "../store/auth";
import { BASE_URL } from "./config";

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  // Nécessaire seulement si le refresh token circule via cookie httpOnly
  // (recommandé — voir note de sécurité). Sans effet si vous restez 100% Bearer.
  withCredentials: true,
});

// --- Corrélation / audit ---------------------------------------------------
// Un id unique par requête facilite le rapprochement des logs frontend
// (Sentry, console) avec les logs backend/iTop lors d'une investigation
// d'incident — utile dès qu'on a plusieurs rôles et donc plusieurs acteurs
// possibles sur une même donnée.
function generateRequestId() {
  return typeof crypto !== "undefined" && crypto.randomUUID
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

apiClient.interceptors.request.use((config) => {
  const { token } = useAuthStore.getState();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  config.headers["X-Request-Id"] = generateRequestId();
  return config;
});

// --- Rafraîchissement de session sans race condition ------------------------
// Problème du code d'origine : si 5 requêtes échouent en 401 en même temps
// (cas fréquent au chargement d'un dashboard multi-widgets), chacune
// déclenchait potentiellement son propre logout/refresh. On sérialise le
// refresh et on met les requêtes en attente derrière une seule promesse.
let refreshPromise = null;

function isAuthEndpoint(url = "") {
  return url.includes("/auth/");
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error;

    if (!response) {
      // Timeout, coupure réseau, CORS... distinct d'une erreur applicative.
      return Promise.reject({ ...error, isNetworkError: true });
    }

    const status = response.status;
    const store = useAuthStore.getState();

    // 401 sur un endpoint non-auth : tenter un refresh unique, une seule fois.
    if (status === 401 && !isAuthEndpoint(config?.url) && !config._retried) {
      config._retried = true;
      try {
        if (!refreshPromise) {
          refreshPromise = store.refresh().finally(() => {
            refreshPromise = null;
          });
        }
        const newToken = await refreshPromise;
        config.headers.Authorization = `Bearer ${newToken}`;
        return apiClient(config);
      } catch (refreshError) {
        // store.refresh() a déjà appelé logout("expired") en cas d'échec
        // définitif — rien à refaire ici, juste propager l'erreur.
        return Promise.reject(refreshError);
      }
    }

    // 403 : session valide mais rôle insuffisant. À NE PAS confondre avec un
    // 401 — ici il ne faut surtout pas déconnecter l'utilisateur. On se
    // contente de marquer l'erreur ; c'est au composant appelant (mutation
    // onError, cf. useAcknowledgeIncident/useResolveIncident) d'afficher le
    // message "vous n'avez pas les droits pour ceci".
    if (status === 403) {
      return Promise.reject({ ...error, isForbidden: true });
    }

    return Promise.reject(error);
  },
);

export default apiClient;
import { create } from "zustand";
import axios from "axios";
import { BASE_URL } from "../api/config";

// Client HTTP délibérément séparé de api/client.js : la logique de refresh
// vit ici (dans le store) pour être partagée par useSessionKeepAlive ET par
// l'intercepteur 401 de client.js sans dépendance circulaire, et sans
// repasser par les intercepteurs Bearer/refresh de apiClient.
const refreshHttp = axios.create({ baseURL: BASE_URL, withCredentials: true });

// Dédoublonnage au niveau module : que le refresh soit déclenché par le
// polling proactif (useSessionKeepAlive) ou par un 401 réactif (client.js),
// les deux partagent le même appel en vol. Important si le refresh token
// tourne (rotation à chaque usage) : deux appels /auth/refresh concurrents
// invalideraient l'un des deux et provoqueraient un logout injustifié.
let inFlightRefresh = null;

export const useAuthStore = create((set, get) => ({
  // Le token d'accès ne vit plus qu'en mémoire — jamais en localStorage.
  // Une fermeture d'onglet le fait disparaître ; c'est voulu. La session est
  // restaurée au chargement via bootstrap(), qui s'appuie sur le refresh
  // token en cookie httpOnly côté serveur (le navigateur l'envoie seul,
  // JS n'y a jamais accès).
  token: null,
  user: null,
  expiresAt: null,
  logoutReason: null,
  // Reste `false` tant qu'on n'a pas tenté la restauration de session au
  // démarrage — permet à l'UI d'afficher un état de chargement plutôt que
  // de flasher l'écran de login avant de savoir si un cookie valide existe.
  bootstrapped: false,

  login: (token, user, expiresIn) =>
    set({
      token,
      user,
      expiresAt: expiresIn ? Date.now() + expiresIn * 1000 : null,
      logoutReason: null,
    }),

  logout: (reason = null) =>
    set({ token: null, user: null, expiresAt: null, logoutReason: reason }),

  clearLogoutReason: () => set({ logoutReason: null }),

  // Tente un rafraîchissement de session. Retourne le nouveau token ou lève
  // si le cookie de refresh est absent/expiré/révoqué. Dédoublonné : un
  // appel déjà en vol est réutilisé plutôt que dupliqué.
  refresh: () => {
    if (!inFlightRefresh) {
      inFlightRefresh = refreshHttp
        .post("/auth/refresh")
        .then(({ data }) => {
          get().login(data.access_token, data.user, data.expires_in);
          return data.access_token;
        })
        .catch((err) => {
          // Échec définitif : cookie de refresh absent/expiré/révoqué.
          // Centralisé ici pour que tout appelant (keep-alive proactif ou
          // intercepteur 401 réactif) obtienne le même comportement sans le
          // dupliquer chacun de son côté.
          get().logout("expired");
          throw err;
        })
        .finally(() => {
          inFlightRefresh = null;
        });
    }
    return inFlightRefresh;
  },

  // À appeler une fois au montage de l'app (voir hooks/useSessionBootstrap.js).
  // Échec silencieux attendu et normal pour un visiteur non connecté — ce
  // n'est pas une erreur à logger.
  bootstrap: async () => {
    try {
      await get().refresh();
    } catch {
      // Pas de cookie valide : l'utilisateur n'est simplement pas connecté.
    } finally {
      set({ bootstrapped: true });
    }
  },
}));
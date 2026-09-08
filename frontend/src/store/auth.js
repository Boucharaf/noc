import axios from "axios";
import { create } from "zustand";

import { BASE_URL } from "../api/config";

// Client HTTP séparé de api/client.js : la logique de refresh vit ici pour
// être partagée par le keep-alive proactif ET par l'intercepteur 401
// réactif, sans dépendance circulaire et sans repasser par les
// intercepteurs qui ont justement besoin d'elle.
const refreshHttp = axios.create({ baseURL: BASE_URL, withCredentials: true });

// Dédoublonnage au niveau module : si le refresh token tourne à chaque
// usage (rotation), deux appels concurrents à /auth/refresh en
// invalideraient un — et déconnecteraient un utilisateur dont la session
// est parfaitement valide.
let inFlight = null;

export const useAuthStore = create((set, get) => ({
  // Le jeton d'accès ne vit qu'en mémoire, jamais en localStorage : un XSS
  // le lirait en une ligne. La session est restaurée au chargement via
  // bootstrap(), qui s'appuie sur le refresh token en cookie httpOnly —
  // le navigateur l'envoie seul, JavaScript n'y a jamais accès.
  token: null,
  user: null,
  expiresAt: null,
  logoutReason: null,
  // Reste `false` tant qu'on n'a pas tenté la restauration : permet
  // d'afficher un écran d'attente plutôt que de faire clignoter la page
  // de connexion avant de savoir si un cookie valide existe.
  bootstrapped: false,

  login: (token, user, expiresIn) =>
    set({
      token,
      user,
      expiresAt: expiresIn ? Date.now() + expiresIn * 1000 : null,
      logoutReason: null,
    }),

  setUser: (user) => set({ user }),

  logout: (reason = null) =>
    set({ token: null, user: null, expiresAt: null, logoutReason: reason }),

  clearLogoutReason: () => set({ logoutReason: null }),

  /**
   * `silent` distingue deux échecs que rien d'autre ne sépare :
   *
   * · une session EN COURS qui tombe (cookie expiré ou révoqué) : il faut
   *   le dire, « Votre session a expiré » explique la déconnexion ;
   * · la restauration au PREMIER chargement, quand il n'y a simplement
   *   aucun cookie. Sans ce drapeau, tout nouveau visiteur découvre
   *   l'écran de connexion avec un message d'expiration parlant d'une
   *   session qui n'a jamais existé.
   *
   * Le motif est posé AVANT que la promesse ne soit rejetée, donc le
   * corriger après coup ne suffit pas : l'écran de connexion l'a déjà lu.
   */
  refresh: (options = {}) => {
    if (!inFlight) {
      const silent = options.silent === true;
      inFlight = refreshHttp
        .post("/auth/refresh")
        .then(({ data }) => {
          get().login(data.access_token, data.user, data.expires_in);
          return data.access_token;
        })
        .catch((error) => {
          get().logout(silent ? null : "expired");
          throw error;
        })
        .finally(() => {
          inFlight = null;
        });
    }
    return inFlight;
  },

  // Appelé une fois au montage. L'échec est le cas NORMAL d'un visiteur
  // non connecté : ce n'est pas une erreur à journaliser.
  bootstrap: async () => {
    try {
      await get().refresh({ silent: true });
    } catch {
      /* pas de cookie valide : le visiteur n'est simplement pas connecté */
    } finally {
      set({ bootstrapped: true });
    }
  },
}));

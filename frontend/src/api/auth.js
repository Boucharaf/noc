import apiClient from "./client";

export const loginWithPassword = (username, password) =>
  apiClient.post("/auth/login", { username, password }).then((r) => r.data);

// Le PIN est un second facteur d'authentification plus faible (4-6 chiffres) :
// à réserver aux rôles terrain à faible risque (ex. Agent terrain sur tablette
// partagée) et JAMAIS pour Directeur/Chef NOC. Le backend doit imposer un
// rate-limit et un verrouillage de compte après N tentatives — voir note de
// sécurité. Ici on se contente de remonter proprement l'état de verrouillage
// pour que l'UI l'affiche sans deviner.
export const loginWithPin = (pin) =>
  apiClient.post("/auth/pin-login", { pin }).then((r) => r.data);
// Réponse attendue en cas d'échec : 423 Locked avec { retry_after_seconds }
// plutôt qu'un simple 401 indistinct d'un mauvais PIN — permet à l'UI
// d'afficher "compte verrouillé, réessayez dans Xs" au lieu d'inciter à
// réessayer immédiatement (ce qui favoriserait le brute-force).

export const refreshSession = () =>
  apiClient.post("/auth/refresh").then((r) => r.data);

export const getMe = () => apiClient.get("/auth/me").then((r) => r.data);

// Invalidation CÔTÉ SERVEUR de la session/refresh token — absent du fichier
// d'origine. Sans cet appel, un logout frontend se contente d'oublier le
// token localement : un refresh token encore valide (souvent long-lived)
// continue de fonctionner s'il a fuité (poste partagé, XSS antérieur, etc.).
export const logout = () => apiClient.post("/auth/logout").then((r) => r.data);

// Permet à Directeur/Chef NOC de révoquer les sessions actives d'un compte
// (poste volé, agent quittant l'agence) sans attendre l'expiration naturelle
// du token. Nécessite l'endpoint backend correspondant + permission MANAGE_USERS.
export const revokeAllSessions = (userId) =>
  apiClient.post(`/auth/users/${userId}/revoke-sessions`).then((r) => r.data);
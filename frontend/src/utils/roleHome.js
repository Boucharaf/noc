import { ROLES } from "../api/permissions";

// Où atterrir juste après connexion, et où rediriger "/". Chaque rôle a un
// écran qui lui est réellement utile en premier — /global exige
// VIEW_KPI_GLOBAL, que Technicien et Agent terrain n'ont pas, donc les y
// envoyer produirait un écran vide/à accès refusé plutôt qu'un atterrissage
// utile.
const HOME_BY_ROLE = {
  [ROLES.DIRECTEUR]: "/global",
  [ROLES.CHEF_NOC]: "/global",
  [ROLES.TECHNICIEN]: "/mes-alertes",
  [ROLES.AGENT_TERRAIN]: "/mes-tournees",
};

export function getHomeRoute(role) {
  return HOME_BY_ROLE[role] ?? "/global";
}

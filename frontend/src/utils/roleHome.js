import { ROLES } from "../api/permissions";

// Où atterrir juste après connexion, et où rediriger "/" — l'écran d'accueil
// de chaque rôle correspond au niveau du document KPI métier qui le concerne
// (Décideur / Chef NOC / Agent NOC / terrain), pas à une liste d'onglets
// génériques identiques pour tout le monde.
const HOME_BY_ROLE = {
  [ROLES.DIRECTEUR]: "/decideur",
  [ROLES.CHEF_NOC]: "/chef-noc",
  [ROLES.TECHNICIEN]: "/incidents",
  [ROLES.AGENT_TERRAIN]: "/tournees",
};

export function getHomeRoute(role) {
  return HOME_BY_ROLE[role] ?? "/decideur";
}

/**
 * RBAC côté interface.
 *
 * ⚠️ Confort d'affichage UNIQUEMENT. La seule autorisation qui compte est
 * celle du backend (`app/dependencies/auth.py::require_role`). Ce module
 * sert à masquer un bouton inutile et à éviter un aller-retour voué au
 * 403 — jamais à protéger une donnée.
 *
 * Chaque entrée ci-dessous est la copie EXACTE d'un tuple de rôles déclaré
 * dans une route backend ; la ligne de commentaire indique laquelle. Toute
 * divergence produit soit un bouton mort (403 au clic), soit une fonction
 * cachée à quelqu'un qui y a droit.
 */
export const ROLES = Object.freeze({
  DIRECTEUR: "directeur",
  CHEF_NOC: "chef_noc",
  TECHNICIEN: "technicien",
  AGENT_TERRAIN: "agent_terrain",
});

export const ROLE_LABEL = Object.freeze({
  directeur: "Directeur",
  chef_noc: "Chef NOC",
  technicien: "Technicien NOC",
  agent_terrain: "Agent terrain",
});

export const ROLE_DESCRIPTION = Object.freeze({
  directeur:
    "Vue de pilotage : disponibilité, SLA, tendances, rapports. Aucun geste d'exploitation.",
  chef_noc:
    "Salle de supervision : affectation, escalade, maintenance, gestion des comptes.",
  technicien:
    "Console d'exploitation : traitement des alertes, acquittement, résolution.",
  agent_terrain:
    "Terrain : tournées, comptes rendus d'intervention, signalement de pannes.",
});

const ALL = [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN];

export const PERMISSIONS = Object.freeze({
  // --- Écrans d'accueil, un par profil ---
  VIEW_DIRECTION: [ROLES.DIRECTEUR],
  VIEW_SUPERVISION: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],
  VIEW_CONSOLE: [ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_TERRAIN: [ROLES.AGENT_TERRAIN, ROLES.CHEF_NOC, ROLES.DIRECTEUR],

  // --- Consultation ---
  // routes/incidents.py::_VIEW_HISTORY — l'agent terrain N'A PAS accès à
  // GET /api/incidents (403). Les écrans terrain passent par /api/alerts.
  VIEW_INCIDENTS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_ALERTS: ALL,
  VIEW_NODES: ALL,
  VIEW_METRICS: ALL,
  VIEW_MAP: ALL,
  VIEW_SLA: ALL,
  VIEW_COVERAGE: ALL,
  VIEW_INTEROP: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],

  // --- Actions sur incident ---
  ACKNOWLEDGE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN], // _ACKNOWLEDGE
  RESOLVE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN], // _RESOLVE
  ASSIGN_INCIDENT: [ROLES.CHEF_NOC], // _ASSIGN — le chef de salle seul répartit
  ESCALATE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN], // _ESCALATE
  COMMENT_INCIDENT: ALL, // get_current_user, aucune restriction de rôle
  CREATE_MANUAL_INCIDENT: ALL, // _MANUAL

  // --- Maintenance ---
  MANAGE_MAINTENANCE: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN], // maintenance.py::_MANAGE

  // --- Terrain ---
  CREATE_FIELD_INTERVENTION: [ROLES.AGENT_TERRAIN, ROLES.CHEF_NOC, ROLES.DIRECTEUR],

  // --- Administration ---
  DOWNLOAD_REPORT: [ROLES.DIRECTEUR, ROLES.CHEF_NOC], // report.py::_DOWNLOAD
  // Le Chef NOC SEUL crée les comptes et attribue les rôles. Chacun modifie
  // ses propres identifiants depuis « Mon compte », qui n'exige aucune
  // permission (auth.py::update_me).
  MANAGE_USERS: [ROLES.CHEF_NOC], // users.py::_MANAGE_USERS
  MANAGE_SLA_TARGETS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC], // sla.py update_target
});

export function hasPermission(role, allowedRoles) {
  if (!Array.isArray(allowedRoles)) return false;
  return allowedRoles.includes(role);
}

/** Écran d'accueil de chaque profil — niveaux 1 à 4 du document métier. */
const HOME_BY_ROLE = {
  [ROLES.DIRECTEUR]: "/direction",
  [ROLES.CHEF_NOC]: "/supervision",
  [ROLES.TECHNICIEN]: "/console",
  [ROLES.AGENT_TERRAIN]: "/terrain",
};

export function homeRoute(role) {
  return HOME_BY_ROLE[role] ?? "/console";
}

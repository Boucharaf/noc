// api/permissions.js
//
// Source de vérité FRONTEND pour le contrôle d'accès basé sur les rôles (RBAC).
//
// ⚠️ IMPORTANT — défense en profondeur uniquement :
// Ce module sert à adapter l'UI (masquer un bouton, désactiver une action,
// éviter un aller-retour réseau inutile). Il ne remplace JAMAIS la
// vérification côté backend. Chaque endpoint sensible (acknowledge, resolve,
// report, users...) DOIT revalider le rôle à partir du JWT/session serveur,
// jamais à partir de ce que le client prétend être.

export const ROLES = Object.freeze({
  DIRECTEUR: "directeur",
  CHEF_NOC: "chef_noc",
  TECHNICIEN: "technicien",
  AGENT_TERRAIN: "agent_terrain",
});

// Matrice permission -> rôles autorisés.
// Ajouter une permission ici la rend automatiquement disponible à
// hasPermission()/useHasPermission() partout dans l'app.
export const PERMISSIONS = Object.freeze({
  // Tableaux de bord par profil (un seul écran d'accueil par rôle)
  VIEW_DECIDEUR_DASHBOARD: [ROLES.DIRECTEUR],
  VIEW_CHEF_NOC_DASHBOARD: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],
  VIEW_INCIDENT_QUEUE: [ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_FIELD_OPS: [ROLES.AGENT_TERRAIN],

  // KPI / supervision transverses
  VIEW_SLA: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_INTEROP_STATUS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_NETWORK_METRICS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_COVERAGE: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_EQUIPMENT_DETAIL: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],

  // Incidents / alertes
  VIEW_ALERTS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],
  VIEW_INCIDENT_HISTORY: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  ACKNOWLEDGE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],
  RESOLVE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  CREATE_MANUAL_INCIDENT: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],

  // Maintenance planifiée
  VIEW_MAINTENANCE_WINDOWS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  CREATE_MAINTENANCE_WINDOW: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],

  // Rapports
  DOWNLOAD_REPORT: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],

  // Administration — le backend autorise directeur ET chef_noc
  // (voir app/routes/users.py::_MANAGE_USERS), pas seulement directeur.
  MANAGE_USERS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],

  // Terrain — propre à l'Agent Terrain (tournées/interventions)
  MANAGE_FIELD_INTERVENTIONS: [ROLES.AGENT_TERRAIN],
});

export class PermissionError extends Error {
  constructor(allowedRoles, role) {
    super(
      `Action refusée : le rôle "${role}" n'est pas autorisé (rôles requis : ${
        Array.isArray(allowedRoles) ? allowedRoles.join(", ") : allowedRoles
      })`
    );
    this.name = "PermissionError";
    this.allowedRoles = allowedRoles;
    this.role = role;
  }
}

/**
 * Vérification pure, sans dépendance au store — testable isolément.
 *
 * `permission` est la VALEUR d'une entrée de PERMISSIONS (un tableau de
 * rôles), pas sa clé.
 */
export function hasPermission(role, allowedRoles) {
  if (!Array.isArray(allowedRoles)) {
    console.warn(`[permissions] Permission invalide référencée :`, allowedRoles);
    return false;
  }
  return allowedRoles.includes(role);
}

/**
 * Garde d'action à utiliser dans la couche API avant un appel sensible.
 * Lève une PermissionError immédiatement au lieu de laisser partir une
 * requête vouée à un 403 — meilleure UX, mais le 403 backend reste le
 * véritable filet de sécurité si ce code est contourné (build ancien, etc.).
 */
export function assertPermission(role, allowedRoles) {
  if (!hasPermission(role, allowedRoles)) {
    throw new PermissionError(allowedRoles, role);
  }
}

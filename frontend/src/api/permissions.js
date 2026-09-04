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
  // Vue d'ensemble / KPI
  VIEW_KPI_GLOBAL: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],
  VIEW_KPI_LOCALITY: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],
  VIEW_SLA: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  VIEW_INTEROP_STATUS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],

  // Incidents / alertes
  VIEW_ALERTS: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],
  ACKNOWLEDGE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN],
  RESOLVE_INCIDENT: [ROLES.CHEF_NOC, ROLES.TECHNICIEN],
  BULK_ACKNOWLEDGE: [ROLES.CHEF_NOC, ROLES.TECHNICIEN],

  // Rapports
  DOWNLOAD_REPORT: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],

  // Administration
  MANAGE_USERS: [ROLES.DIRECTEUR],
  VIEW_AUDIT_LOG: [ROLES.DIRECTEUR, ROLES.CHEF_NOC],
  VIEW_DATA_MODEL: [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN],

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
 * rôles), pas sa clé — c'est l'usage réel dans tout le code (voir
 * api/alerts.js, hooks/usePermission.js) : hasPermission(role,
 * PERMISSIONS.ACKNOWLEDGE_INCIDENT), jamais hasPermission(role,
 * "ACKNOWLEDGE_INCIDENT"). Une implémentation antérieure faisait
 * PERMISSIONS[permission] (donc attendait la clé) : incohérent avec tous
 * ses appelants, qui échouaient silencieusement (fail-closed) — corrigé ici.
 */
export function hasPermission(role, allowedRoles) {
  if (!Array.isArray(allowedRoles)) {
    // Permission mal référencée = on refuse par défaut (fail-closed), pas l'inverse.
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
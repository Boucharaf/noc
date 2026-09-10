/**
 * Contrat d'API — miroir exact des routes du backend.
 *
 * Tout regroupé dans UN fichier, et pas un module par domaine : c'est le
 * document de référence qui doit rester aligné avec `backend/app/routes/`.
 * Éclaté en quinze fichiers de six lignes, la dérive entre les deux côtés
 * passe inaperçue ; ici un `git diff` sur les routes backend se compare
 * ligne à ligne avec celui-ci.
 *
 * ─────────────────────────────────────────────────────────────────────────
 *  CE QUI A CHANGÉ AVEC L'ARCHITECTURE « INSTANTANÉ + FÉDÉRATION »
 * ─────────────────────────────────────────────────────────────────────────
 *
 * 1. UN INCIDENT N'A PLUS D'IDENTIFIANT NUMÉRIQUE. Il est désigné par la
 *    clé que le collecteur lui donne : `<outil>:<référence>`, par exemple
 *    `zabbix:1042`. Cette clé contient un deux-points : elle DOIT être
 *    encodée avec encodeURIComponent avant d'entrer dans une URL, sinon le
 *    routeur du backend la coupe au séparateur.
 *
 * 2. LE VOCABULAIRE PASSE D'« INCIDENT » À « ALERTE ». Ce n'est pas
 *    cosmétique : une alerte est ce que remonte un outil de supervision,
 *    un incident était une ligne dans une table que le NOC recopiait. Les
 *    anciens noms de fonctions sont conservés en alias là où le frontend
 *    les utilise encore, avec un commentaire.
 *
 * 3. IL N'Y A PLUS DE RÉFÉRENTIEL GÉOGRAPHIQUE. Régions, localités et
 *    ministères n'existaient que dans l'entrepôt supprimé. Le site d'un
 *    équipement vient désormais des outils sources (groupes Zabbix ou
 *    Centreon nommés « Site/… », Location iTop) et se lit directement sur
 *    l'équipement. `geo.*` est remplacé par `sites.list()`.
 *
 * 4. LES COURBES INTERROGENT L'OUTIL SOURCE. `metrics.nodeSeries` part vers
 *    Zabbix ou Centreon et peut échouer si l'outil est indisponible — elle
 *    répond alors 502 avec le nom de l'outil. Ne jamais la placer sur un
 *    écran qui se rafraîchit tout seul.
 *
 * Aucune fonction ne fait de traitement : elles renvoient `data` brut. La
 * mise en forme vit dans `lib/format.js`, le cache et le polling dans
 * `hooks/queries.js`.
 */
import apiClient from "./client";

const get = (url, params) => apiClient.get(url, { params }).then((r) => r.data);
const post = (url, body) => apiClient.post(url, body).then((r) => r.data);
const patch = (url, body) => apiClient.patch(url, body).then((r) => r.data);
const put = (url, body) => apiClient.put(url, body).then((r) => r.data);
const del = (url, config) => apiClient.delete(url, config).then((r) => r.data);

/**
 * Encodage d'une clé d'alerte ou d'équipement pour une URL.
 *
 * `zabbix:1042` contient un deux-points, `centreon:host-3` un tiret : sans
 * encodage, le premier casse le routage côté backend. Cette fonction existe
 * pour qu'on ne l'oublie nulle part.
 */
const key = (value) => encodeURIComponent(String(value));

/* ------------------------------------------------------------------ */
/* Authentification et comptes                                         */
/* ------------------------------------------------------------------ */
export const auth = {
  login: (username, password) => post("/auth/login", { username, password }),
  pinLogin: (pin) => post("/auth/pin-login", { pin }),
  logout: () => post("/auth/logout"),
  me: () => get("/auth/me"),
  /**
   * Ses propres identifiants : username, full_name, phone_number, email,
   * notify_email. `current_password` n'est exigé que pour changer
   * d'identifiant. Le rôle est refusé (422) — seul le Chef NOC l'attribue.
   */
  updateMe: (payload) => patch("/auth/me", payload),
  changePassword: (current_password, new_password) =>
    patch("/auth/me/password", { current_password, new_password }),
  revokeSessions: (userId) => post(`/auth/users/${userId}/revoke-sessions`),
};

/** Gestion des comptes — Chef NOC uniquement, sauf `list`. */
export const users = {
  list: () => get("/users"),
  create: (payload) => post("/users", payload),
  update: (userId, payload) => patch(`/users/${userId}`, payload),
  deactivate: (userId) => post(`/users/${userId}/deactivate`),
  resetPin: (userId, new_pin) => post(`/users/${userId}/reset-pin`, { new_pin }),
  resetPassword: (userId, new_password) =>
    post(`/users/${userId}/reset-password`, { new_password }),
};

/* ------------------------------------------------------------------ */
/* Vue d'ensemble — tout vient de l'instantané Redis                    */
/* ------------------------------------------------------------------ */
export const overview = {
  /** Tuiles de tête : parc, alertes, fraîcheur de la collecte. */
  summary: () => get("/overview"),
  /** Synthèse par site, du plus dégradé au plus sain. */
  sites: () => get("/sites"),
  alertsBySeverity: () => get("/alerts/by-severity"),
  alertsByTool: () => get("/alerts/by-tool"),
  hourDistribution: () => get("/alerts/hour-distribution"),
};

/** Remplace l'ancien `geo` : le site n'est plus une entité du NOC. */
export const sites = {
  list: () => get("/sites"),
};

/* ------------------------------------------------------------------ */
/* Alertes                                                              */
/* ------------------------------------------------------------------ */
export const alerts = {
  /**
   * @param {object} params
   *   severity, tool, site, acknowledged, include_maintenance, limit
   */
  list: (params) => get("/alerts", params),
  get: (alertKey) => get(`/alerts/${key(alertKey)}`),

  acknowledge: (alertKey, note) =>
    post(`/alerts/${key(alertKey)}/acknowledge`, { note }),
  assign: (alertKey, assignee_id, note) =>
    post(`/alerts/${key(alertKey)}/assign`, { assignee_id, note }),
  /**
   * Clôture CÔTÉ NOC. Ne ferme rien chez l'outil source : si l'alerte y
   * reste active, elle reste visible, marquée comme traitée.
   */
  resolve: (alertKey, cause, note) =>
    post(`/alerts/${key(alertKey)}/resolve`, { cause, note }),
  addNote: (alertKey, note) => post(`/alerts/${key(alertKey)}/note`, { note }),
};

/** Incidents signalés à la main, qu'aucune sonde ne voit. */
export const manualIncidents = {
  create: (payload) => post("/manual-incidents", payload),
  resolve: (id) => post(`/manual-incidents/${id}/resolve`),
};

/**
 * Alias de compatibilité pour les écrans écrits avant le changement de
 * vocabulaire. `incidents` et `alerts` désignent la même chose.
 *
 * `exportCsv` est produit ICI, dans le navigateur, et non par le backend.
 * L'ancien export passait par une route `/incidents/export.csv` qui
 * balayait la table des faits ; cette table n'existe plus, et le mur
 * d'alertes est déjà entièrement chargé côté client — l'exporter est une
 * transformation de tableau, pas une requête.
 */
export const incidents = {
  ...alerts,
  createManual: manualIncidents.create,
  exportCsv: async (params) => {
    const { alerts: rows = [] } = await alerts.list(params);
    const columns = [
      ["key", "Clé"],
      ["tool", "Outil"],
      ["severity", "Gravité"],
      ["node_name", "Équipement"],
      ["site", "Site"],
      ["message", "Message"],
      ["since", "Depuis"],
      ["acknowledged", "Acquittée"],
      ["acknowledged_by", "Acquittée par"],
      ["cause", "Cause"],
      ["is_maintenance", "Maintenance planifiée"],
    ];
    // Guillemets doublés et champ entouré : un message de sonde contient
    // très souvent des virgules et des sauts de ligne (la sortie de
    // check_ping en est un bon exemple), qui casseraient le fichier.
    const escape = (value) =>
      `"${String(value ?? "").replace(/"/g, '""')}"`;
    const lines = [
      columns.map(([, label]) => escape(label)).join(","),
      ...rows.map((row) => columns.map(([field]) => escape(row[field])).join(",")),
    ];
    // BOM UTF-8 : sans lui, Excel ouvre le fichier en ANSI et les accents
    // deviennent illisibles.
    return new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
  },
};

/* ------------------------------------------------------------------ */
/* Équipements                                                          */
/* ------------------------------------------------------------------ */
export const nodes = {
  /** @param {object} params state, site, tool, search, sort, limit, offset */
  list: (params) => get("/nodes", params),
  states: () => get("/nodes/states"),
  /**
   * Couverture par outil, et nombre d'équipements vus par UN SEUL outil —
   * autant de points de rupture : si cet outil tombe, on les perd de vue
   * sans que rien ne le signale.
   */
  coverage: () => get("/nodes/coverage"),
  get: (nodeId) => get(`/nodes/${key(nodeId)}`),
};

/* ------------------------------------------------------------------ */
/* Réseau et métriques                                                  */
/* ------------------------------------------------------------------ */
export const metrics = {
  /** Instantané : lecture Redis, jamais en échec tant que la collecte tourne. */
  snapshot: () => get("/network/snapshot"),
  down: () => get("/network/down"),
  top: (limit) => get("/network/top", { limit }),

  /**
   * ⚠️ INTERROGE L'OUTIL SOURCE. Peut répondre 502 si Zabbix ou Centreon
   * est indisponible — le corps porte alors `{error, tool, message}`.
   * À n'appeler que sur une action explicite de l'exploitant.
   */
  nodeSeries: (nodeId, { metric, period } = {}) =>
    get(`/nodes/${key(nodeId)}/metrics`, { metric, period }),
  networkSeries: ({ metric, period, sample } = {}) =>
    get("/network/series", { metric, period, sample }),
};

/* ------------------------------------------------------------------ */
/* Tendances — agrégats journaliers, pas d'appel aux outils sources      */
/* ------------------------------------------------------------------ */
export const kpi = {
  /** @param {object} params days, site */
  trend: (params) => get("/kpi/trend", params),
  /** @param {object} params year, month, site */
  monthly: (params) => get("/kpi/monthly", params),
  sites: (params) => get("/kpi/sites", params),
  /** Causes retenues par les exploitants — la seule analyse propre au NOC. */
  causes: (params) => get("/kpi/causes", params),
  resolutionTimes: (params) => get("/kpi/resolution-times", params),
};

/* ------------------------------------------------------------------ */
/* Engagements de service                                               */
/* ------------------------------------------------------------------ */
export const sla = {
  targets: () => get("/sla/targets"),
  updateTarget: (severity, payload) => put(`/sla/targets/${severity}`, payload),
  compliance: (params) => get("/sla/compliance", params),
  breaches: (params) => get("/sla/breaches", params),
  /** Alertes en cours qui vont manquer leur objectif — le seul actionnable. */
  atRisk: () => get("/sla/at-risk"),
};

/* ------------------------------------------------------------------ */
/* Maintenance                                                          */
/* ------------------------------------------------------------------ */
export const maintenance = {
  /** @param {string} scope all | active | upcoming | past */
  list: (scope = "all") => get("/maintenance", { scope }),
  create: (payload) => post("/maintenance", payload),
  remove: (windowId) => del(`/maintenance/${windowId}`),
};

/* ------------------------------------------------------------------ */
/* Terrain                                                              */
/* ------------------------------------------------------------------ */
export const field = {
  list: (params) => get("/field/interventions", params),
  get: (id) => get(`/field/interventions/${id}`),
  create: (payload) => post("/field/interventions", payload),
  update: (id, payload) => patch(`/field/interventions/${id}`, payload),
};

/* ------------------------------------------------------------------ */
/* Interopérabilité — l'état de la chaîne de collecte                   */
/* ------------------------------------------------------------------ */
export const interop = {
  /**
   * Reste servi même quand tout le reste ne l'est plus : c'est exactement
   * le moment où l'exploitant en a besoin.
   */
  status: () => get("/interop/status"),
  /** Détail des rapprochements multi-outils. */
  merge: () => get("/interop/merge"),
};

/* ------------------------------------------------------------------ */
/* Notifications et rapports                                            */
/* ------------------------------------------------------------------ */
export const notifications = {
  vapidPublicKey: () => get("/notifications/vapid-public-key"),
  subscribe: (subscription) => post("/notifications/subscribe", subscription),
  /** Configuration SMTP et destinataires effectifs — Chef NOC. */
  emailStatus: () => get("/notifications/email/status"),
  /**
   * Envoie un courriel de test. Sans `to`, aux destinataires des alertes.
   * Répond 502 avec le message du serveur SMTP si l'envoi échoue.
   */
  sendTestEmail: (to) => post("/notifications/email/test", to?.length ? { to } : {}),
};

export const report = {
  monthly: ({ month, year, format = "pdf" } = {}) =>
    apiClient.get("/report/monthly", {
      params: { month, year, format },
      responseType: "blob",
    }),
};

export const health = () => get("/health");

export default {
  auth,
  users,
  overview,
  sites,
  alerts,
  incidents,
  manualIncidents,
  nodes,
  metrics,
  kpi,
  sla,
  maintenance,
  field,
  interop,
  notifications,
  report,
  health,
};

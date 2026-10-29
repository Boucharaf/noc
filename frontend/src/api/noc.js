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
/** Journal d'audit — lecture seule (Chef NOC, Directeur). */
export const audit = {
  /** @param {object} params action, user_id, limit, offset */
  list: (params) => get("/audit", params),
};

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
  /**
   * Tuiles de tête : parc, alertes, incidents iTop, fraîcheur de la
   * collecte — sur le périmètre (`region`, `province`, `site`, `search`).
   */
  summary: (params) => get("/overview", params),
  /** Synthèse par site, du plus dégradé au plus sain. */
  sites: (params) => get("/sites", params),
  /** Disponibilité par organisation (ministère, structure) du périmètre. */
  organisations: (params) => get("/organisations", params),
  alertsByTool: (params) => get("/alerts/by-tool", params),
  /** Alertes en cours par ancienneté (tranches). */
  alertAges: (params) => get("/alerts/ages", params),
  hourDistribution: (params) => get("/alerts/hour-distribution", params),
};

/** Remplace l'ancien `geo` : le site n'est plus une entité du NOC. */
export const sites = {
  list: (params) => get("/sites", params),
};

/* ------------------------------------------------------------------ */
/* Alertes                                                              */
/* ------------------------------------------------------------------ */
export const alerts = {
  /**
   * @param {object} params
   *   severity, kind, tool, site, acknowledged, include_maintenance, limit
   */
  list: (params) => get("/alerts", params),
  get: (alertKey) => get(`/alerts/${key(alertKey)}`),
  // Lecture seule : le traitement et les affectations sont tenus dans iTop.
};

/* ------------------------------------------------------------------ */
/* Territoire — région > province > site > nœud                         */
/* ------------------------------------------------------------------ */
export const geo = {
  /** Arbre des localités du parc réel, pour les sélecteurs en cascade. */
  options: () => get("/geo/options"),
  /** Le périmètre et ses subdivisions immédiates, avec leurs indicateurs. */
  breakdown: (params) => get("/geo/breakdown", params),
  site: (site) => get(`/geo/sites/${key(site)}`),
};

/* ------------------------------------------------------------------ */
/* Incidents — iTop UNIQUEMENT (les alertes viennent des outils)        */
/* ------------------------------------------------------------------ */
export const itopIncidents = {
  /** @param {object} params region, province, site, search, severity, status, limit */
  list: (params) => get("/incidents", params),
  /**
   * ⚠️ INTERROGE iTop (tickets ouverts sur la période, clos ou non), cache de 5 min.
   * @param {object} params days, region, province, site, search, severity, status, offset, limit
   */
  history: (params) => get("/incidents/history", params),
  /** Ticket iTop + vue des outils sur l'équipement + alertes associées. */
  get: (incidentKey) => get(`/incidents/${key(incidentKey)}`),
  /**
   * ⚠️ INTERROGE iTop (tickets résolus de la période), cache de 5 min.
   * @param {object} params group_by (region|province|site|node), days, region, province, site
   */
  sla: (params) => get("/sla/incidents", params),
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
  states: (params) => get("/nodes/states", params),
  /**
   * Couverture par outil, et nombre d'équipements vus par UN SEUL outil —
   * autant de points de rupture : si cet outil tombe, on les perd de vue
   * sans que rien ne le signale.
   */
  coverage: (params) => get("/nodes/coverage", params),
  get: (nodeId) => get(`/nodes/${key(nodeId)}`),
};

/* ------------------------------------------------------------------ */
/* Réseau et métriques                                                  */
/* ------------------------------------------------------------------ */
export const metrics = {
  /** Instantané : lecture Redis, jamais en échec tant que la collecte tourne. */
  snapshot: (params) => get("/network/snapshot", params),
  /** Historique court (24 h, un point par cycle de collecte), lu dans Redis. */
  trend: (params) => get("/trend/live", params),
  down: (params) => get("/network/down", params),
  top: (limit, params) => get("/network/top", { limit, ...params }),

  /**
   * ⚠️ INTERROGE L'OUTIL SOURCE. Peut répondre 502 si Zabbix ou Centreon
   * est indisponible — le corps porte alors `{error, tool, message}`.
   * À n'appeler que sur une action explicite de l'exploitant.
   */
  nodeSeries: (nodeId, { metric, period } = {}) =>
    get(`/nodes/${key(nodeId)}/metrics`, { metric, period }),
  nodeLatest: (nodeId) => get(`/nodes/${key(nodeId)}/metrics-latest`),
  networkSeries: (params = {}) => get("/network/series", params),
};

/* ------------------------------------------------------------------ */
/* Tendances — agrégats journaliers, pas d'appel aux outils sources      */
/* ------------------------------------------------------------------ */
export const kpi = {
  /** @param {object} params days, site */
  trend: (params) => get("/kpi/trend", params),
  /** @param {object} params year, month, site */
  monthly: (params) => get("/kpi/monthly", params),
  /** @param {object} params days, limit, sort (availability | alerts) */
  sites: (params) => get("/kpi/sites", params),
  /**
   * Indicateurs d'incidents iTop de la période : volumes, résolution,
   * récurrence, causes, réouvertures, organisations. ⚠️ Lit l'historique iTop.
   * @param {object} params days, region, province, site
   */
  incidents: (params) => get("/kpi/incidents", params),
};

/* ------------------------------------------------------------------ */
/* Engagements de service                                               */
/* ------------------------------------------------------------------ */
export const sla = {
  targets: () => get("/sla/targets"),
  updateTarget: (severity, payload) => put(`/sla/targets/${severity}`, payload),
  /**
   * Incidents iTop ouverts qui vont manquer leur objectif — le seul
   * actionnable. @param {object} params region, province, site
   */
  atRisk: (params) => get("/sla/at-risk", params),
  /** Engagements contractuels (SLT) déclarés dans iTop — interroge iTop. */
  contract: () => get("/sla/contract"),
};

/* ------------------------------------------------------------------ */
/* Maintenance                                                          */
/* ------------------------------------------------------------------ */
export const maintenance = {
  /** @param {string} scope all | active | upcoming | past */
  /** Changements iTop et maintenances Zabbix — lecture seule.
   * @param {object} params scope (all|active|upcoming|past), region, province, site, search */
  list: (params) => get("/maintenance", params),
};

/* ------------------------------------------------------------------ */
/* Terrain                                                              */
/* ------------------------------------------------------------------ */
/** Suggestions des barres de recherche, lues dans l'instantané. */
export const search = {
  /** @param {object} params q, kinds (liste séparée par des virgules), limit */
  suggest: (params) => get("/search/suggest", params),
};

/** Interventions : ordres de travail iTop — lecture seule. */
export const interventions = {
  /** @param {object} params status (all|open|closed), region, province, site, search */
  list: (params) => get("/interventions", params),
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
    }).then((response) => response.data),
};

export const health = () => get("/health");

/* ------------------------------------------------------------------ */
/* Historique de disponibilité (journal du collecteur, base du NOC)     */
/* ------------------------------------------------------------------ */
export const history = {
  status: () => get("/history/status"),
  /** Disponibilité, pannes, liens et alertes d'un équipement sur `days` jours. */
  node: (nodeId, days = 30) => get(`/history/nodes/${encodeURIComponent(nodeId)}`, { days }),
  /** Équipements (kind=node) ou liens (kind=link) les moins disponibles. */
  ranking: (params) => get("/history/ranking", params),
};

export default {
  auth,
  users,
  audit,
  overview,
  sites,
  alerts,
  incidents,
  nodes,
  metrics,
  kpi,
  sla,
  maintenance,
  interventions,
  search,
  interop,
  notifications,
  report,
  health,
  history,
};

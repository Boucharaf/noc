/**
 * Vocabulaire métier partagé : sévérités, statuts, états d'équipement,
 * métriques, outils sources.
 *
 * Un seul endroit pour chaque correspondance « valeur backend → libellé
 * français + couleur ». Dupliquer ces tables dans chaque page produit
 * immanquablement un écran où « high » s'affiche « Élevé » et un autre
 * « Majeur », avec deux oranges différents — le genre d'incohérence qui
 * fait douter un exploitant de ce qu'il lit.
 *
 * Les couleurs sont des variables CSS et non des hex : le thème clair les
 * redéfinit, et une valeur codée en dur ici y deviendrait illisible.
 */

/* ------------------------------------------------------------------ */
/* Sévérité — vocabulaire NORMALISÉ produit par la vue v_incident      */
/* ------------------------------------------------------------------ */
export const SEVERITIES = ["critical", "high", "medium", "low", "info", "unknown"];

export const SEVERITY = {
  critical: { label: "Critique", short: "CRIT", color: "var(--sev-critical)", rank: 0 },
  high: { label: "Majeur", short: "MAJ", color: "var(--sev-high)", rank: 1 },
  medium: { label: "Moyen", short: "MOY", color: "var(--sev-medium)", rank: 2 },
  low: { label: "Mineur", short: "MIN", color: "var(--sev-low)", rank: 3 },
  info: { label: "Information", short: "INFO", color: "var(--sev-info)", rank: 4 },
  unknown: { label: "Inconnu", short: "?", color: "var(--sev-unknown)", rank: 5 },
};

export const severityMeta = (value) => SEVERITY[value] ?? SEVERITY.unknown;

/* ------------------------------------------------------------------ */
/* Statut d'incident                                                    */
/* ------------------------------------------------------------------ */
export const STATUSES = ["open", "acknowledged", "resolved", "closed"];

export const STATUS = {
  open: { label: "Ouvert", color: "var(--sev-critical)" },
  acknowledged: { label: "Acquitté", color: "var(--sev-medium)" },
  resolved: { label: "Résolu", color: "var(--state-up)" },
  closed: { label: "Clos", color: "var(--ink-3)" },
};

export const statusMeta = (value) => STATUS[value] ?? { label: value ?? "—", color: "var(--ink-3)" };

/* ------------------------------------------------------------------ */
/* État d'un équipement — dérivé par backend/app/services/node_service  */
/* ------------------------------------------------------------------ */
export const NODE_STATES = ["down", "degraded", "silent", "maintenance", "up", "inactive"];

export const NODE_STATE = {
  down: {
    label: "Hors service",
    color: "var(--state-down)",
    hint: "Incident bloquant ouvert, ou disponibilité mesurée nulle.",
  },
  degraded: {
    label: "Dégradé",
    color: "var(--state-degraded)",
    hint: "Incident ouvert, ou seuil dépassé (dispo < 99 %, pertes > 5 %, CPU/RAM > 90 %).",
  },
  silent: {
    label: "Muet",
    color: "var(--state-silent)",
    hint: "Aucune métrique reçue depuis 6 h — l'outil de supervision ne remonte plus rien.",
  },
  maintenance: {
    label: "Maintenance",
    color: "var(--state-maintenance)",
    hint: "Couvert par une fenêtre de maintenance planifiée : alertes neutralisées.",
  },
  up: { label: "Nominal", color: "var(--state-up)", hint: "Aucun incident, seuils respectés." },
  inactive: {
    label: "Désactivé",
    color: "var(--state-inactive)",
    hint: "Marqué inactif dans l'inventaire — hors périmètre de supervision.",
  },
};

export const nodeStateMeta = (value) =>
  NODE_STATE[value] ?? { label: value ?? "—", color: "var(--ink-3)", hint: "" };

/* ------------------------------------------------------------------ */
/* Métriques — miroir de etl/transform/normalize_metrics.py            */
/* ------------------------------------------------------------------ */
export const METRICS = {
  availability_pct: {
    label: "Disponibilité",
    unit: "%",
    digits: 2,
    // `higherIsBetter` pilote à la fois le sens des classements et la
    // couleur d'un seuil franchi : sans lui, une latence basse
    // s'afficherait en rouge.
    higherIsBetter: true,
    target: 99,
    color: "var(--state-up)",
  },
  latency_ms: {
    label: "Latence",
    unit: "ms",
    digits: 0,
    higherIsBetter: false,
    target: 100,
    color: "var(--sev-info)",
  },
  packet_loss_pct: {
    label: "Perte de paquets",
    unit: "%",
    digits: 2,
    higherIsBetter: false,
    target: 2,
    color: "var(--sev-high)",
  },
  cpu_pct: {
    label: "CPU",
    unit: "%",
    digits: 0,
    higherIsBetter: false,
    target: 80,
    color: "var(--sev-medium)",
  },
  ram_pct: {
    label: "Mémoire",
    unit: "%",
    digits: 0,
    higherIsBetter: false,
    target: 85,
    color: "var(--state-maintenance)",
  },
  bandwidth_in_mbps: {
    label: "Trafic entrant",
    unit: "Mb/s",
    digits: 1,
    higherIsBetter: null, // ni bon ni mauvais : c'est une charge, pas un score
    target: null,
    color: "var(--accent)",
  },
  bandwidth_out_mbps: {
    label: "Trafic sortant",
    unit: "Mb/s",
    digits: 1,
    higherIsBetter: null,
    target: null,
    color: "var(--sev-low)",
  },
};

export const METRIC_TYPES = Object.keys(METRICS);

export const metricMeta = (type) =>
  METRICS[type] ?? { label: type, unit: "", digits: 2, higherIsBetter: null, target: null };

/**
 * Couleur d'une valeur selon son seuil métier.
 * Renvoie `null` quand la métrique n'a pas de seuil (trafic) : l'appelant
 * doit alors garder l'encre neutre plutôt que d'inventer un verdict.
 */
export function thresholdColor(metricType, value) {
  const meta = metricMeta(metricType);
  if (value === null || value === undefined || meta.target === null) return null;
  const v = Number(value);
  if (meta.higherIsBetter) {
    if (v >= meta.target) return "var(--state-up)";
    if (v >= meta.target - 2) return "var(--sev-medium)";
    return "var(--sev-critical)";
  }
  if (v <= meta.target) return "var(--state-up)";
  if (v <= meta.target * 1.5) return "var(--sev-medium)";
  return "var(--sev-critical)";
}

/** Couleur d'un taux de disponibilité (99 % = objectif RESINA). */
export function availabilityColor(value) {
  if (value === null || value === undefined) return "var(--ink-3)";
  if (value >= 99) return "var(--state-up)";
  if (value >= 97) return "var(--sev-medium)";
  if (value >= 90) return "var(--sev-high)";
  return "var(--sev-critical)";
}

/* ------------------------------------------------------------------ */
/* Outils sources                                                       */
/* ------------------------------------------------------------------ */
export const TOOL_LABEL = {
  zabbix: "Zabbix",
  itop: "iTop",
  netxms: "NetXMS",
  centreon: "Centreon",
  nagios: "Nagios",
  nsp: "Nokia NSP",
  manual: "Saisie manuelle",
  demo: "Démonstration",
};

export const toolLabel = (tool) => TOOL_LABEL[tool] ?? tool ?? "—";

/* ------------------------------------------------------------------ */
/* État d'un collecteur ETL (services/interop_service.py)              */
/* ------------------------------------------------------------------ */
export const TOOL_STATE = {
  ok: { label: "Actif", color: "var(--state-up)" },
  stale: { label: "En retard", color: "var(--sev-medium)" },
  error: { label: "En erreur", color: "var(--sev-critical)" },
  not_configured: { label: "Non configuré", color: "var(--ink-3)" },
  unknown: { label: "Jamais collecté", color: "var(--state-silent)" },
};

export const toolStateMeta = (state) =>
  TOOL_STATE[state] ?? { label: state ?? "—", color: "var(--ink-3)" };

/* ------------------------------------------------------------------ */
/* Statuts d'intervention terrain                                       */
/* ------------------------------------------------------------------ */
export const FIELD_STATUS = {
  scheduled: { label: "Planifiée", color: "var(--ink-2)" },
  en_route: { label: "En route", color: "var(--sev-info)" },
  on_site: { label: "Sur site", color: "var(--sev-medium)" },
  done: { label: "Terminée", color: "var(--state-up)" },
  cancelled: { label: "Annulée", color: "var(--ink-3)" },
};

export const fieldStatusMeta = (status) =>
  FIELD_STATUS[status] ?? { label: status ?? "—", color: "var(--ink-3)" };

/* ------------------------------------------------------------------ */
/* Actions de la chronologie d'un incident                              */
/* ------------------------------------------------------------------ */
export const TIMELINE_ACTION = {
  created: "Création",
  acknowledged: "Acquittement",
  assigned: "Affectation",
  escalated: "Escalade",
  commented: "Commentaire",
  resolved: "Résolution",
  reopened: "Réouverture",
};

export const timelineActionLabel = (action) => TIMELINE_ACTION[action] ?? action;

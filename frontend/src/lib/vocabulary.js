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
  critical: { label: "Critique", plural: "Critiques", short: "CRIT", color: "var(--sev-critical)", rank: 0 },
  // Accord au féminin (« une gravité, une alerte ») — INC-17 : une seule
  // échelle, écrite pareil partout.
  high: { label: "Majeure", plural: "Majeures", short: "MAJ", color: "var(--sev-high)", rank: 1 },
  medium: { label: "Moyenne", plural: "Moyennes", short: "MOY", color: "var(--sev-medium)", rank: 2 },
  low: { label: "Mineure", plural: "Mineures", short: "MIN", color: "var(--sev-low)", rank: 3 },
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
/* État d'un équipement — miroir de integrations/models.py::NODE_STATES */
/* ------------------------------------------------------------------ */
// « unknown » DOIT figurer ici : sans lui, les équipements à l'état inconnu
// (états contradictoires entre outils, CI vus par la seule CMDB) n'étaient
// comptés dans aucune tuile, et le total ne se retrouvait pas.
// « silent » (muet) est fusionné dans « unknown » par le collecteur.
export const NODE_STATES = ["down", "degraded", "maintenance", "up", "unknown"];

export const NODE_STATE = {
  down: {
    label: "Hors service",
    color: "var(--state-down)",
    hint: "L'outil de supervision constate l'équipement injoignable.",
  },
  degraded: {
    label: "Perturbé",
    color: "var(--state-degraded)",
    hint: "Répond, mais avec des anomalies : pertes de paquets, service en défaut.",
  },
  // Fusionné dans « Inconnu » : un équipement dont l'outil ne remonte plus
  // rien n'est ni en marche ni en panne connue.
  silent: {
    label: "Inconnu",
    color: "var(--state-unknown)",
    hint: "État non mesuré : l'outil ne remonte rien sur cet équipement.",
  },
  maintenance: {
    label: "Maintenance",
    color: "var(--state-maintenance)",
    hint: "Couvert par une fenêtre de maintenance planifiée : exclu du calcul de disponibilité.",
  },
  up: { label: "Normal", color: "var(--state-up)", hint: "En service." },
  unknown: {
    label: "Inconnu",
    color: "var(--state-unknown)",
    hint: "État non mesuré : rien ne remonte sur cet équipement, ou il n'est connu que de l'inventaire.",
  },
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
    label: "Débit up",
    unit: "Mb/s",
    digits: 1,
    higherIsBetter: null, // ni bon ni mauvais : c'est une charge, pas un score
    target: null,
    color: "var(--accent)",
  },
  bandwidth_out_mbps: {
    label: "Débit down",
    unit: "Mb/s",
    digits: 1,
    higherIsBetter: null,
    target: null,
    color: "var(--sev-low)",
  },
  disk_pct: {
    label: "Disque", unit: "%", digits: 0, higherIsBetter: false, target: 90, color: "var(--sev-high)",
  },
  temp_cpu: {
    label: "Temp. CPU", unit: "°C", digits: 1, higherIsBetter: false, target: 75, color: "var(--sev-high)",
  },
  cpu_load: {
    label: "Charge (Load)", unit: "", digits: 2, higherIsBetter: false, target: null, color: "var(--sev-info)",
  },
  proc_count: {
    label: "Processus", unit: "", digits: 0, higherIsBetter: null, target: null, color: "var(--ink-2)",
  },
  uptime: {
    label: "Uptime", unit: " j", digits: 1, higherIsBetter: true, target: null, color: "var(--state-up)",
  },
  if_errors: {
    label: "Err. réseau", unit: "", digits: 0, higherIsBetter: false, target: 0, color: "var(--sev-critical)",
  },
  dci_custom: {
    label: "Sonde divers", unit: "", digits: 1, higherIsBetter: null, target: null, color: "var(--accent)",
  },
  rssi: {
    label: "Signal Radio", unit: "dBm", digits: 0, higherIsBetter: true, target: -70, color: "var(--state-up)",
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

/**
 * Seuils [vert, orange] de l'agence (feuille « KPI NOC référence ») :
 * KPI-01 pour la disponibilité sur la durée (cœur, accès), KPI-02 pour le
 * parc en service. Valeurs par défaut ; le backend publie celles qui sont
 * configurées (AVAILABILITY_THRESHOLDS_*, FLEET_THRESHOLDS).
 */
export const THRESHOLDS = { core: [99.9, 99], access: [99, 97], fleet: [98, 90] };

export function applyThresholds(values) {
  for (const key of Object.keys(THRESHOLDS)) {
    if (Array.isArray(values?.[key]) && values[key].length === 2) THRESHOLDS[key] = values[key];
  }
}

function levelColor(value, [green, orange]) {
  if (value === null || value === undefined) return "var(--ink-3)";
  if (value >= green) return "var(--state-up)";
  if (value >= orange) return "var(--sev-medium)";
  return "var(--sev-critical)";
}

const shown = (value) => String(value).replace(".", ",");

/** Cible affichée sous une tuile : « ≥ 99 % ». */
export function thresholdTarget(kind) {
  return `≥ ${shown(THRESHOLDS[kind][0])} %`;
}

/** Disponibilité sur la durée (KPI-01). Sans classe connue : accès. */
export function availabilityColor(value, kind = "access") {
  return levelColor(value, THRESHOLDS[kind] ?? THRESHOLDS.access);
}

/** « cœur 98,20 % · accès 73,10 % » : leurs seuils diffèrent (KPI-01). */
export function classHint(classes) {
  const parts = [["core", "cœur"], ["access", "accès"]]
    .filter(([key]) => classes?.[key]?.average_pct != null)
    .map(([key, label]) => `${label} ${classes[key].average_pct.toFixed(2).replace(".", ",")} %`);
  return parts.length ? parts.join(" · ") : undefined;
}

/** Parc en service à l'instant (KPI-02). */
export function fleetColor(value) {
  return levelColor(value, THRESHOLDS.fleet);
}

/** Légende des couleurs du parc en service : [couleur, libellé]. */
export function fleetLegend() {
  const [green, orange] = THRESHOLDS.fleet;
  return [
    ["var(--state-up)", `≥ ${shown(green)} %`],
    ["var(--sev-medium)", `${shown(orange)}–${shown(green)} %`],
    ["var(--sev-critical)", `< ${shown(orange)} % ou ≥ 1 panne / critique`],
  ];
}

/* ------------------------------------------------------------------ */
/* Type d'équipement (INC-33, AM-32)                                    */
/* ------------------------------------------------------------------ */
// Les outils publient leurs valeurs brutes, en anglais et à des niveaux
// différents : « host » (Centreon), « NetworkDevice » (classe iTop),
// « 7750 SR-7 » (un MODÈLE Nokia, pas un type). Un seul dictionnaire, en
// français ; une valeur qui ressemble à une référence de modèle est
// affichée comme modèle d'un « Équipement réseau ».
const NODE_TYPE = {
  host: "Hôte",
  networkdevice: "Équipement réseau",
  router: "Routeur",
  switch: "Commutateur",
  firewall: "Pare-feu",
  server: "Serveur",
  virtualmachine: "Machine virtuelle",
  vm: "Machine virtuelle",
  pc: "Poste de travail",
  printer: "Imprimante",
  storagesystem: "Stockage",
  nas: "Stockage",
  san: "Stockage",
  wifi: "Borne Wi-Fi",
  accesspoint: "Borne Wi-Fi",
  ups: "Onduleur",
  ne: "Équipement réseau",
};

export function nodeTypeInfo(raw) {
  if (!raw) return { type: null, model: null };
  const key = String(raw).replace(/[\s_-]/g, "").toLowerCase();
  if (NODE_TYPE[key]) return { type: NODE_TYPE[key], model: null };
  // « 7750 SR-7 », « 7210 SAS-M » : une référence de modèle.
  if (/\d/.test(raw)) return { type: "Équipement réseau", model: String(raw) };
  return { type: String(raw), model: null };
}

export const nodeTypeLabel = (raw) => nodeTypeInfo(raw).type;

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

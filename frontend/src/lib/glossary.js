/**
 * Glossaire des indicateurs — l'infobulle « ? » de chaque tuile (INC-37,
 * AM-24, AM-33), rédigée pour un décideur : une définition en une phrase,
 * le calcul, la source.
 *
 * Une tuile sans `help` explicite trouve ici son texte par son libellé
 * (`helpFor`). Le libellé est normalisé : casse, accents et précision de
 * période entre parenthèses (« Respect des SLA (30 j) ») n'y comptent pas.
 * Ajouter un indicateur = ajouter une entrée ici, pas dans chaque écran.
 */
const ENTRIES = [
  {
    labels: ["parc en service", "parc en service (instantane)", "disponibilite du parc"],
    definition: "Part des équipements supervisés qui fonctionnent à cet instant.",
    formula: "en service ÷ supervisés (en service + dégradés + en panne)",
    source: "état courant des outils de supervision",
    note: "Les équipements non supervisés et en maintenance sont comptés à part. Ce n'est pas la disponibilité sur la durée.",
  },
  {
    labels: ["disponibilite", "disponibilite moyenne"],
    definition: "Part du temps où les équipements ont répondu sur la période.",
    formula: "temps où l'équipement répond (en service ou perturbé) ÷ temps supervisé, pondéré par équipement",
    source: "journal historique du NOC (un relevé par cycle de collecte)",
    note: "Le temps sans observation (non supervisé) n'est compté ni pour ni contre. Seuils : cœur 99,9 / 99 %, accès 99 / 97 % (à valider par la direction).",
  },
  {
    labels: ["equipements hs", "equipements en panne", "en panne", "hors service"],
    definition: "Équipements dont un outil confirme la panne.",
    formula: "nombre d'équipements à l'état « hors service »",
    source: "outils de supervision",
    note: "Un équipement non supervisé n'est jamais compté en panne.",
  },
  {
    labels: ["equip. supervises", "equipements supervises"],
    definition: "Équipements dont l'état est réellement observé par un outil.",
    formula: "en service + dégradés + en panne",
    source: "outils de supervision",
  },
  {
    labels: ["equipements non supervises", "etat inconnu"],
    definition: "Équipements qu'aucun outil n'observe actuellement : leur état n'est pas démontré.",
    formula: "inconnus + muets",
    source: "outils de supervision et CMDB iTop",
    note: "Comptés à part : ni en service, ni en panne.",
  },
  {
    labels: ["equipements", "equipements connus"],
    definition: "Équipements du périmètre, tous états confondus.",
    source: "inventaire fusionné des outils",
  },
  {
    labels: ["mesures non collectees"],
    definition: "Mesures qu'aucun outil branché ne publie pour ce périmètre.",
    source: "Zabbix, Centreon",
    note: "Une mesure non collectée n'est pas à zéro : elle est inconnue.",
  },
  {
    labels: ["incidents iTop ouverts", "incidents ouverts", "incidents", "incidents itop", "ouvertes"],
    definition: "Tickets d'incident iTop non résolus et non clos.",
    source: "iTop",
  },
  {
    labels: ["critiques", "majeurs", "majeures", "haute priorite"],
    definition: "Incidents ou alertes de cette gravité, en cours.",
    source: "iTop (incidents) ou outils de supervision (alertes)",
  },
  {
    labels: ["non affectes", "non affectees"],
    definition: "Tickets qu'aucun agent ne traite encore.",
    formula: "tickets ouverts sans agent affecté",
    source: "iTop",
    note: "Objectif : zéro pour les critiques.",
  },
  {
    labels: ["respect des sla", "conformite sla"],
    definition: "Part des incidents traités dans le délai promis.",
    formula: "incidents dans les délais ÷ incidents évalués",
    source: "iTop (objectifs de délai par gravité)",
    note: "Cible : 95 % ou plus.",
  },
  {
    labels: ["sla depasse"],
    definition: "Tickets ouverts dont le délai de résolution est déjà dépassé.",
    source: "iTop",
    note: "Non évaluable si iTop ne répond pas.",
  },
  {
    labels: ["mttr", "mttr moyen", "mttr des alertes", "duree moyenne d'une panne", "resolution moy."],
    definition: "Temps moyen pour rétablir le service après une panne (Mean Time To Repair).",
    formula: "moyenne de (fin de panne − début de panne)",
    source: "journal historique ou iTop",
    note: "Exemple : 3 pannes de 1 h, 2 h et 3 h donnent un MTTR de 2 h.",
  },
  {
    labels: ["mtbf moyen", "entre deux pannes (mtbf)", "mtbf"],
    definition: "Temps moyen de bon fonctionnement entre deux pannes (Mean Time Between Failures).",
    formula: "temps en service ÷ nombre de pannes",
    source: "journal historique du NOC",
    note: "Plus il est élevé, plus l'équipement est fiable.",
  },
  {
    labels: ["pannes"],
    definition: "Nombre de périodes continues de panne sur la période.",
    source: "journal historique du NOC",
  },
  {
    labels: ["a traiter"],
    definition: "Alertes actives non encore acquittées par l'équipe.",
    source: "outils de supervision",
  },
  {
    labels: ["non acquittes"],
    definition: "Alertes actives que personne n'a encore prises en compte.",
    source: "outils de supervision",
  },
  {
    labels: ["> 24 h", "plus ancien non acq."],
    definition: "Alertes actives depuis plus de 24 heures, ou âge de la plus ancienne non acquittée.",
    source: "outils de supervision",
    note: "Au-delà de 30 jours, une alerte est marquée « À revoir ».",
  },
  {
    labels: ["sites touches"],
    definition: "Sites ayant au moins un équipement en panne ou une alerte active.",
    source: "outils de supervision",
  },
  {
    labels: ["alertes outils", "alertes actives (moy.)", "critiques actives (moy.)"],
    definition: "Alertes techniques émises par les outils de supervision.",
    source: "Zabbix, Centreon, NetXMS, Nagios, Nokia NSP",
  },
  {
    labels: ["incidents resolus", "cloturees", "terminees"],
    definition: "Éléments clos sur la période.",
    source: "iTop",
  },
  {
    labels: ["nouveaux (1 h)"],
    definition: "Tickets ouverts au cours de la dernière heure.",
    source: "iTop",
  },
  {
    labels: ["liens surveilles actifs", "liens surveilles coupes"],
    definition: "Liens que l'outil attend actifs, et ceux d'entre eux qui sont coupés.",
    source: "NetXMS (état réel des interfaces)",
    note: "« Non surveillé » si aucun lien attendu n'est déclaré.",
  },
  {
    labels: ["interfaces activees actives"],
    definition: "Part des interfaces activées qui transmettent.",
    formula: "interfaces activées en service ÷ interfaces activées mesurées",
    source: "NetXMS",
    note: "Ports libres compris : un port activé sans câble compte comme inactif sans être en panne.",
  },
  {
    labels: ["capacite active", "capacite installee"],
    definition: "Débit nominal cumulé des interfaces en service.",
    source: "NetXMS",
    note: "Capacité installée, pas débit utilisé.",
  },
  {
    labels: ["en cours", "a venir", "equipements en maintenance"],
    definition: "Maintenances planifiées et équipements concernés.",
    source: "iTop (changements) et Zabbix (maintenances)",
    note: "Un équipement en maintenance sort du calcul de disponibilité.",
  },
  {
    labels: ["outils actifs"],
    definition: "Outils sources qui ont répondu au dernier cycle de collecte.",
    source: "collecteur du NOC",
  },
  {
    labels: ["intervalle de collecte"],
    definition: "Temps entre deux interrogations des outils sources.",
    source: "configuration du collecteur",
  },
];

const normalise = (label) =>
  String(label ?? "")
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s*\((?:\d+\s*(?:h|j|mois)|instantane)\)\s*$/, "")
    .trim();

const INDEX = new Map();
for (const entry of ENTRIES) {
  for (const label of entry.labels) INDEX.set(normalise(label), entry);
}

/** Texte de l'infobulle d'un indicateur, ou undefined s'il n'est pas décrit. */
export function helpFor(label) {
  if (typeof label !== "string") return undefined;
  const entry = INDEX.get(normalise(label));
  if (!entry) return undefined;
  return [
    entry.definition,
    entry.formula && `Calcul : ${entry.formula}.`,
    entry.source && `Source : ${entry.source}.`,
    entry.note,
  ]
    .filter(Boolean)
    .join(" ");
}

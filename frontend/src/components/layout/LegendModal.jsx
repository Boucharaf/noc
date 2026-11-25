import { Modal } from "../ui/Overlay";
import { NodeStateBadge, SeverityBadge } from "../ui/Badge";

// Règle de chaque état (AM-25, INC-04) : ce qu'il faut pour l'afficher.
const STATE_RULES = [
  ["up", "un outil a observé l'équipement récemment et il répond. Jamais déduit de la seule absence d'alerte."],
  ["degraded", "il répond, avec des anomalies (pertes, service en défaut)."],
  ["down", "un outil confirme qu'il est injoignable."],
  ["unknown", "aucune observation récente (outil muet, CMDB seule, états contradictoires). Ni en service, ni en panne : compté à part."],
  ["maintenance", "couvert par une maintenance planifiée : exclu des taux."],
];

/**
 * Légende commune du NOC : ce que veulent dire les couleurs et les mots.
 *
 * Une seule page de référence plutôt que des explications éparpillées :
 * un nouvel exploitant l'ouvre une fois et lit ensuite tous les écrans de
 * la même façon.
 */
const MEANING = [
  ["var(--state-up)", "Vert", "Tout va bien : normal, dans les délais, objectif tenu."],
  ["var(--sev-medium)", "Orange", "À surveiller : perturbé, proche du seuil, en attente."],
  ["var(--sev-critical)", "Rouge", "Action requise : en panne, critique, hors délai."],
  ["var(--state-maintenance)", "Violet", "Maintenance planifiée (iTop ou Zabbix) : coupure voulue, exclue des indicateurs."],
  ["var(--ink-3)", "Gris", "Pas de donnée : non collecté, inconnu, sans objectif."],
];

const GLOSSARY = [
  ["Incident", "Ticket ouvert dans iTop : une prise en charge, avec un responsable et un délai. Les incidents ne viennent que d'iTop."],
  ["Alerte", "Signal technique d'un outil de supervision (Zabbix, Centreon, NetXMS, Nagios, NSP). Elle explique un incident, elle n'en est pas un."],
  ["Parc en service", "À l'instant : équipements en service ÷ équipements supervisés. Maintenance et non supervisés sont comptés à part."],
  ["Disponibilité", "Sur une période : temps où l'équipement répond (en service ou perturbé) ÷ temps supervisé, pondéré par équipement."],
  ["Non supervisé", "Aucune observation récente : état inconnu. Jamais compté en panne, jamais dans le dénominateur des taux."],
  ["Inconnu", "Rien ne remonte sur l'équipement : on ne sait pas s'il marche. Compté à part (non supervisé), jamais comme une panne."],
  ["À revoir", "Alerte active depuis plus de 30 jours sans acquittement : équipement retiré ou alerte oubliée."],
  ["Perturbé", "L'équipement répond, mais avec des anomalies : pertes de paquets, service en défaut."],
  ["Gravité d'une alerte", "Affichée telle que l'outil la classe (« Désastre », « Majeure »…) ; la couleur suit l'échelle commune."],
  ["TTO", "Délai de prise en charge : de l'ouverture du ticket à son affectation à un agent."],
  ["TTR", "Délai de résolution : de l'ouverture du ticket à sa résolution."],
  ["SLA", "Engagement de délai par gravité. « Respect » = part des incidents résolus dans leur délai."],
  ["Mini-courbe", "Évolution sur la période choisie dans la barre de filtres."],
  ["Pastille « Balé · 30 j »", "Périmètre et période appliqués au bloc ; « instantané » = l'état à cet instant."],
  ["Repère sur une jauge", "L'objectif à atteindre (ou à ne pas dépasser)."],
];

export default function LegendModal({ open, onClose }) {
  return (
    <Modal open={open} onClose={onClose} title="Légende du NOC" subtitle="couleurs, états et vocabulaire" width={720}>
      <div className="grid gap-4 sm:grid-cols-2">
        <section>
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] mb-1.5" style={{ color: "var(--ink-3)" }}>
            Couleurs
          </h3>
          <ul className="space-y-1.5">
            {MEANING.map(([color, name, text]) => (
              <li key={name} className="flex gap-2 text-[12px]">
                <span className="shrink-0 mt-[3px]" style={{ width: 12, height: 12, borderRadius: 3, background: color }} />
                <span><strong>{name}</strong> — {text}</span>
              </li>
            ))}
          </ul>

          <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] mt-3 mb-1.5" style={{ color: "var(--ink-3)" }}>
            États des équipements
          </h3>
          <ul className="space-y-1 text-[12px]">
            {STATE_RULES.map(([state, rule]) => (
              <li key={state} className="flex items-start gap-2">
                <span className="shrink-0" style={{ minWidth: 104 }}>
                  <NodeStateBadge state={state} />
                </span>
                <span style={{ color: "var(--ink-2)" }}>{rule}</span>
              </li>
            ))}
          </ul>

          <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] mt-3 mb-1.5" style={{ color: "var(--ink-3)" }}>
            Gravité (incidents et alertes)
          </h3>
          <div className="flex flex-wrap gap-1.5 text-[12px]">
            {["critical", "high", "medium", "low", "info"].map((severity) => (
              <SeverityBadge key={severity} severity={severity} />
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.07em] mb-1.5" style={{ color: "var(--ink-3)" }}>
            Vocabulaire
          </h3>
          <dl className="space-y-1.5 text-[12px]">
            {GLOSSARY.map(([term, text]) => (
              <div key={term}>
                <dt className="font-semibold inline">{term} : </dt>
                <dd className="inline" style={{ color: "var(--ink-2)" }}>{text}</dd>
              </div>
            ))}
          </dl>
          <p className="text-[12px] mt-2" style={{ color: "var(--ink-3)" }}>
            Le « ? » à côté d'un indicateur en donne la définition au survol.
          </p>
        </section>
      </div>
    </Modal>
  );
}

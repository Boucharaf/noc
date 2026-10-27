import { Modal } from "../ui/Overlay";
import { nodeStateMeta, severityMeta } from "../../lib/vocabulary";

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
  ["Disponibilité", "Part des équipements suivis qui répondent, hors maintenance planifiée."],
  ["Inconnu", "Rien ne remonte sur l'équipement : on ne sait pas s'il marche. Compté comme non disponible."],
  ["Perturbé", "L'équipement répond, mais avec des anomalies : pertes de paquets, service en défaut."],
  ["Gravité d'une alerte", "Affichée telle que l'outil la classe (« Désastre », « Majeure »…) ; la couleur suit l'échelle commune."],
  ["TTO", "Délai de prise en charge : de l'ouverture du ticket à son affectation à un agent."],
  ["TTR", "Délai de résolution : de l'ouverture du ticket à sa résolution."],
  ["SLA", "Engagement de délai par gravité. « Respect » = part des incidents résolus dans leur délai."],
  ["Mini-courbe", "Évolution sur les dernières 24 h."],
  ["Repère sur une jauge", "L'objectif à atteindre (ou à ne pas dépasser)."],
];

export default function LegendModal({ open, onClose }) {
  return (
    <Modal open={open} onClose={onClose} title="Légende du NOC" subtitle="couleurs, états et vocabulaire" width={720}>
      <div className="grid gap-4 sm:grid-cols-2">
        <section>
          <h3 className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mb-1.5" style={{ color: "var(--ink-3)" }}>
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

          <h3 className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mt-3 mb-1.5" style={{ color: "var(--ink-3)" }}>
            États des équipements
          </h3>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]">
            {["up", "degraded", "down", "maintenance", "unknown"].map((state) => (
              <span key={state} className="flex items-center gap-1">
                <span className="dot" style={{ background: nodeStateMeta(state).color }} />
                {nodeStateMeta(state).label}
              </span>
            ))}
          </div>

          <h3 className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mt-3 mb-1.5" style={{ color: "var(--ink-3)" }}>
            Gravité (incidents et alertes)
          </h3>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]">
            {["critical", "high", "medium", "low"].map((severity) => (
              <span key={severity} className="flex items-center gap-1">
                <span className="dot" style={{ background: severityMeta(severity).color }} />
                {severityMeta(severity).label}
              </span>
            ))}
          </div>
        </section>

        <section>
          <h3 className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mb-1.5" style={{ color: "var(--ink-3)" }}>
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
          <p className="text-[11px] mt-2" style={{ color: "var(--ink-3)" }}>
            Le « ? » à côté d'un indicateur en donne la définition au survol.
          </p>
        </section>
      </div>
    </Modal>
  );
}

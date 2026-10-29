import Panel from "../ui/Panel";
import { DefRow, Meter } from "../ui/Stat";
import { bandwidth, dateTime, duration, num, pct } from "../../lib/format";
import { thresholdColor, toolLabel } from "../../lib/vocabulary";

/**
 * Fiche technique d'un équipement : ce que chaque outil en dit au-delà de son
 * état — inventaire matériel, disponibilité calculée par l'agence dans
 * NetXMS, état des interfaces. Champ `details` de l'instantané, par outil
 * (integrations/models.py, Node.details).
 *
 * Purement descriptif : rien ici ne décide de l'état ni des décomptes.
 */
const INVENTORY_LABELS = [
  ["vendor", "Constructeur"],
  ["model", "Modèle"],
  ["serial", "N° de série"],
  ["os", "Système"],
  ["type", "Type"],
  ["location", "Emplacement déclaré"],
];

function Inventory({ facts }) {
  return INVENTORY_LABELS.filter(([key]) => facts[key]).map(([key, label]) => (
    <DefRow key={key} label={label} mono={key === "serial"}>
      {facts[key]}
    </DefRow>
  ));
}

function Availability({ facts }) {
  return (
    <>
      <div className="flex justify-between text-[11px] mb-1">
        <span style={{ color: "var(--ink-3)" }}>Disponibilité (calcul de l'agence)</span>
        <span className="num">{pct(facts.pct, 2)}</span>
      </div>
      <Meter value={facts.pct} color={thresholdColor("availability_pct", facts.pct)} />
      <div className="mt-1.5">
        <DefRow label="Pannes comptées">{num(facts.failures)}</DefRow>
        <DefRow label="MTTR">{duration(facts.mttr_h != null ? facts.mttr_h * 60 : null)}</DefRow>
        <DefRow label="MTBF">{duration(facts.mtbf_h != null ? facts.mtbf_h * 60 : null)}</DefRow>
        {facts.computed_at && <DefRow label="Calculée le">{dateTime(facts.computed_at)}</DefRow>}
      </div>
    </>
  );
}

function Interfaces({ facts }) {
  const watchedUp = facts.watched - facts.watched_down;
  return (
    <>
      <DefRow label="Interfaces">{num(facts.total)}</DefRow>
      <DefRow label="Activées">
        {num(facts.enabled)}
        <span className="ml-1.5 text-[11px]" style={{ color: "var(--ink-3)" }}>
          {num(facts.enabled_up, "0")} actives · {num(facts.enabled_down, "0")} inactives
        </span>
      </DefRow>
      {facts.watched > 0 && (
        <DefRow label="Liens surveillés">
          <span style={{ color: facts.watched_down ? "var(--sev-high)" : undefined }}>
            {num(watchedUp)} / {num(facts.watched)} actifs
          </span>
        </DefRow>
      )}
      {facts.capacity_bps > 0 && (
        <DefRow label="Capacité active">{bandwidth(facts.capacity_bps / 1e6)}</DefRow>
      )}
    </>
  );
}

export default function SourceFacts({ details }) {
  const sources = Object.entries(details ?? {}).filter(
    ([, facts]) => facts && (facts.inventory || facts.availability || facts.interfaces),
  );
  if (!sources.length) return null;
  return (
    <Panel title="Fiche technique" subtitle="inventaire, disponibilité et interfaces, par outil">
      <div className="space-y-3">
        {sources.map(([tool, facts]) => (
          <section key={tool}>
            {sources.length > 1 && (
              <h3
                className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mb-1"
                style={{ color: "var(--ink-3)" }}
              >
                {toolLabel(tool)}
              </h3>
            )}
            {facts.inventory && <Inventory facts={facts.inventory} />}
            {facts.interfaces && <Interfaces facts={facts.interfaces} />}
            {facts.availability && (
              <div className="mt-2">
                <Availability facts={facts.availability} />
              </div>
            )}
          </section>
        ))}
      </div>
    </Panel>
  );
}

import Panel from "../ui/Panel";
import { duration, num, pct } from "../../lib/format";
import { useGeoOptions, useItopIncidents, useOverview } from "../../hooks/queries";

/**
 * Qualité des données (AM-12, zone Z6 de la maquette).
 *
 * Trois chiffres dont dépendent TOUS les autres : si les tickets ne sont pas
 * rattachés à un équipement, la carte des incidents est fausse ; si
 * l'inventaire n'a ni type ni site, les regroupements le sont ; si la
 * collecte est ancienne, tout l'écran l'est.
 */
function tone(value, good, fair) {
  if (value === null || value === undefined) return "var(--ink-3)";
  if (value >= good) return "var(--state-up)";
  if (value >= fair) return "var(--sev-medium)";
  return "var(--sev-critical)";
}

function Row({ label, value, color, detail, help }) {
  return (
    <li className="flex items-baseline gap-2 px-2.5 py-1.5" title={help}>
      <span className="text-[12px] flex-1 min-w-0">
        {label}
        {detail && (
          <span className="block text-[12px]" style={{ color: "var(--ink-3)" }}>
            {detail}
          </span>
        )}
      </span>
      <span className="num font-semibold text-[13px]" style={{ color }}>
        {value}
      </span>
    </li>
  );
}

export default function DataQuality() {
  const overview = useOverview();
  const incidents = useItopIncidents({ limit: 1 });
  const options = useGeoOptions();
  const variants = options.data?.site_spelling_variants ?? [];
  const o = overview.data;
  const i = incidents.data;
  const ageMinutes = o?.snapshot_age_s != null ? o.snapshot_age_s / 60 : null;

  return (
    <Panel title="Qualité des données" scope={{ period: "live" }} flush>
      <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
        <Row
          label="Tickets rattachés à un équipement"
          value={pct(i?.attachment_rate_pct, 0)}
          color={tone(i?.attachment_rate_pct, 95, 80)}
          detail={i && `cible ≥ 95 % · ${num(i.network_unlocated)} ticket(s) sans équipement`}
          help="Part des tickets iTop ouverts liés à un équipement (CI). Un ticket non rattaché ne peut être placé ni sur la carte ni dans une région."
        />
        <Row
          label="Couverture de supervision (CMDB)"
          value={pct(o?.cmdb_coverage_pct, 0)}
          color={tone(o?.cmdb_coverage_pct, 95, 80)}
          detail={
            o?.cmdb_nodes
              ? `cible ≥ 95 % · ${num(o.cmdb_supervised)} / ${num(o.cmdb_nodes)} équipements iTop supervisés`
              : "aucun équipement de la CMDB iTop dans le périmètre"
          }
          help="Équipements de la CMDB iTop réellement observés par un outil de supervision, rapportés à tous les équipements de la CMDB. Détecte les zones aveugles."
        />
        <Row
          label="Inventaire complet (type et site)"
          value={pct(o?.inventory_complete_pct, 0)}
          color={tone(o?.inventory_complete_pct, 95, 80)}
          detail={
            o &&
            `${num(o.inventory_missing_type)} sans type · ${num(o.inventory_missing_site)} sans site`
          }
          help="Équipements dont le type et le site sont connus. Sans eux, impossible de regrouper par type, de situer sur la carte ou d'appliquer des seuils par type."
        />
        <Row
          label="Noms hors convention"
          value={num(o?.naming_nonconforming)}
          color={o?.naming_nonconforming ? "var(--sev-medium)" : "var(--state-up)"}
          detail={
            o?.naming_nonconforming
              ? `ex. ${(o.naming_examples ?? []).join(", ")}`
              : "tous les noms suivent la convention SITE-RÔLE-NN"
          }
          help="Équipements dont le nom ne suit pas la convention de l'agence (SITE-RÔLE-NN, par exemple PA-RTR-01). Une convention commune permet de situer et de typer un équipement à la seule lecture de son nom. Règle réglable : NODE_NAME_PATTERN."
        />
        <Row
          label="Sites écrits de plusieurs façons"
          value={num(variants.length)}
          color={variants.length ? "var(--sev-medium)" : "var(--state-up)"}
          detail={
            variants.length
              ? variants
                  .slice(0, 3)
                  .map((item) => item.names.join(" / "))
                  .join(" · ") + (variants.length > 3 ? " …" : "")
              : "aucun doublon d'écriture"
          }
          help="Sites dont le nom diffère seulement par les accents ou la casse selon l'outil (« Zôrgho » / « Zorgho »). À harmoniser dans l'outil source : le NOC ne réécrit pas le référentiel."
        />
        <Row
          label="Fraîcheur de la collecte"
          value={ageMinutes == null ? "—" : duration(ageMinutes)}
          color={o?.stale ? "var(--sev-critical)" : "var(--state-up)"}
          detail={o?.stale ? "collecte interrompue : chiffres figés" : "âge du dernier instantané"}
          help="Temps écoulé depuis le dernier cycle de collecte. Au-delà de deux cycles, les chiffres de l'écran ne sont plus à jour."
        />
        <Row
          label="Équipements non supervisés"
          value={num(o?.nodes_unsupervised)}
          color={o?.nodes_unsupervised ? "var(--sev-medium)" : "var(--state-up)"}
          detail="sans observation récente, comptés à part"
          help="Équipements qu'aucun outil n'observe actuellement (état inconnu). Ils ne comptent ni en service ni en panne."
        />
      </ul>
    </Panel>
  );
}

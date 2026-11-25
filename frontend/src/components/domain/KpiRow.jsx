import Stat from "../ui/Stat";
import { availabilityColor, classHint, thresholdTarget } from "../../lib/vocabulary";
import { complianceColor } from "../../lib/itop";
import { num, pct } from "../../lib/format";
import {
  useHistoryRanking,
  useKpiTrend,
  useLiveTrend,
  useOverview,
  useSlaIncidents,
} from "../../hooks/queries";
import { useWindowStore, windowDays, windowLabel } from "../../store/ui";
import { usePermission } from "../../hooks/useSession";
import { PERMISSIONS } from "../../lib/permissions";

/**
 * Rangée des 6 indicateurs clés — zone Z2 de la maquette (AM-02, AM-04).
 *
 *   Santé réseau · Disponibilité · Équipements HS · Incidents ouverts ·
 *   Alertes critiques non acquittées · SLA respecté
 *
 * Toutes les tuiles suivent le même moule (AM-04) : valeur, cible, tendance
 * ou détail, et en pied la FENÊTRE et la SOURCE. Une tuile sans donnée dit
 * pourquoi (« Non évaluable », AM-23) au lieu d'afficher « — ».
 */
const COMPONENT_LABEL = {
  availability: "disponibilité",
  incidents: "incidents",
  alerts: "alertes critiques",
  coverage: "couverture",
};

function healthColor(score) {
  if (score === null || score === undefined) return "#b3b9db";
  if (score >= 90) return "#6fd4a3";
  if (score >= 75) return "#f5c46b";
  return "#ff8a80";
}

function healthHelp(health, o) {
  const parts = [
    "Indice 0–100 qui résume l'état du réseau en un chiffre.",
    "Calcul (pondérations proposées, à valider par la direction) : 40 % disponibilité, 20 % incidents (−10 points par incident critique ouvert), 20 % alertes critiques (−10 points par alerte critique non acquittée), 20 % couverture de supervision.",
  ];
  if (health?.components) {
    parts.push(
      `Détail : ${Object.entries(health.components)
        .map(([key, value]) => `${COMPONENT_LABEL[key]} ${value == null ? "non mesurée" : Math.round(value)}`)
        .join(", ")}.`,
    );
  }
  if (health?.score != null) {
    parts.push(
      o?.health_availability_basis === "period"
        ? `Disponibilité : temps où les équipements répondent ÷ temps supervisé, ${o.health_availability_days === 1 ? "24 dernières heures" : `${o.health_availability_days} derniers jours`}.`
        : "Journal historique vide : le parc en service à l'instant remplace la disponibilité.",
    );
  }
  if (health?.missing?.length) {
    parts.push(
      `Composante(s) écartée(s), faute de donnée : ${health.missing.map((key) => COMPONENT_LABEL[key]).join(", ")}.`,
    );
  }
  return parts.join(" ");
}

export default function KpiRow() {
  const hours = useWindowStore((s) => s.hours);
  const days = windowDays(hours);
  const period = windowLabel(hours);
  const overview = useOverview();
  const history = useHistoryRanking({ kind: "node", days, limit: 1 });
  const sla = useSlaIncidents({ days });
  const live = useLiveTrend();
  const daily = useKpiTrend(days);

  const o = overview.data;
  const health = o?.health;
  const availability = history.data?.available ? history.data.average_pct : null;
  const downSpark =
    hours > 24 ? (daily.data ?? []).map((row) => row.down) : live.data?.nodesDown;
  const totals = sla.data?.totals;
  const critical = o?.alerts_critical_unacknowledged;
  // Même rangée sur les quatre tableaux de bord : un lien n'est posé que si
  // le profil a droit à l'écran visé (l'agent terrain n'a pas /incidents).
  const canNodes = usePermission(PERMISSIONS.VIEW_NODES);
  const canIncidents = usePermission(PERMISSIONS.VIEW_INCIDENTS);
  const canAlerts = usePermission(PERMISSIONS.VIEW_ALERTS);
  const canSla = usePermission(PERMISSIONS.VIEW_SLA);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-3.5">
      <Stat
        emphasis
        label="Santé réseau"
        value={health?.score == null ? "Non évaluable" : `${health.score}`}
        unit={health?.score == null ? undefined : "/ 100"}
        color={healthColor(health?.score)}
        target="≥ 90"
        hint={
          health?.score == null
            ? "aucun équipement supervisé"
            : health.missing?.length
              ? `sans ${health.missing.map((key) => COMPONENT_LABEL[key]).join(", ")}`
              : undefined
        }
        gauge={health?.score != null ? { value: health.score, target: 90, max: 100 } : undefined}
        help={healthHelp(health, o)}
        footer="instantané · calcul NOC"
      />
      <Stat
        label="Disponibilité"
        value={availability == null ? "Non évaluable" : pct(availability, 2)}
        color={availabilityColor(availability)}
        target={thresholdTarget("access")}
        hint={
          availability == null
            ? history.data?.available === false
              ? "journal historique indisponible"
              : "historique en construction"
            : classHint(history.data.classes) ??
              `parc en service à l'instant : ${pct(o?.fleet_availability_pct, 1)}`
        }
        footer={`${period} · journal historique`}
        sources="fleet"
      />
      <Stat
        label="Équipements HS"
        value={num(o ? (o.nodes_by_state?.down ?? 0) : null)}
        color={o?.nodes_by_state?.down ? "var(--state-down)" : "var(--state-up)"}
        hint={o?.nodes_unsupervised ? `${num(o.nodes_unsupervised)} non supervisé(s) à part` : undefined}
        spark={downSpark}
        invertDelta
        footer="instantané · outils de supervision"
        to={canNodes ? "/equipements?state=down" : undefined}
      />
      <Stat
        label="Incidents ouverts"
        value={num(o?.incidents_total)}
        color={o?.incidents_critical ? "var(--sev-critical)" : undefined}
        hint={o && `${num(o.incidents_critical)} critique(s) · ${num(o.incidents_unassigned)} non affecté(s)`}
        footer="instantané · iTop"
        sources="incidents"
        to={canIncidents ? "/incidents" : undefined}
      />
      <Stat
        label="Alertes critiques non acquittées"
        value={num(critical)}
        color={critical ? "var(--sev-critical)" : "var(--state-up)"}
        hint={o?.alerts_obsolete ? `dont ${num(o.alerts_obsolete_critical)} à revoir (> 30 j)` : undefined}
        help="Alertes critiques des outils que personne n'a encore prises en compte. Celles actives depuis plus de 30 jours sont marquées « À revoir »."
        footer="instantané · outils de supervision"
        sources="alerts"
        to={canAlerts ? "/alertes?severity=critical" : undefined}
      />
      <Stat
        label="SLA respecté"
        value={
          sla.isError
            ? "Non évaluable"
            : totals?.compliance_pct == null
              ? "Non évaluable"
              : pct(totals.compliance_pct, 1)
        }
        color={complianceColor(totals?.compliance_pct)}
        target="≥ 95 %"
        hint={
          sla.isError
            ? "historique iTop indisponible"
            : totals?.compliance_pct == null
              ? "aucun incident évalué"
              : `sur ${num(totals.evaluated)} incident(s) évalué(s)`
        }
        help="Part des incidents résolus dans leur délai, parmi les incidents évalués : résolus avec un objectif, ou encore ouverts mais déjà hors délai."
        footer={`${period} · iTop`}
        sources="sla"
        to={canSla ? "/sla" : undefined}
      />
    </div>
  );
}

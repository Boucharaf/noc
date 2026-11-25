import { toolLabel } from "./vocabulary";

/**
 * Dépendance des indicateurs envers les outils sources (INC-24, AM-23).
 *
 * Quand un outil est en erreur, les tuiles qui en dépendent le disent
 * (« iTop en erreur — données de 10:42 ») au lieu d'afficher un « — » ou un
 * chiffre périmé sans explication. Une seule table, lue par toutes les
 * tuiles, pour que le bandeau de situation et les tuiles disent la même
 * chose.
 */
const SUPERVISION = ["zabbix", "centreon", "netxms", "nagios", "nsp"];

export const SOURCE_DEPENDENCIES = {
  incidents: ["itop"],
  sla: ["itop"],
  // Latence, pertes, débits, CPU… : publiés par Zabbix et Centreon.
  metrics: ["zabbix", "centreon"],
  // États du parc et alertes techniques : tous les outils de supervision.
  fleet: SUPERVISION,
  alerts: SUPERVISION,
  // Interfaces et disponibilité calculée par l'agence : NetXMS.
  links: ["netxms"],
};

/** Ce qu'une source en erreur rend incomplet, pour le bandeau de situation. */
const IMPACT = {
  itop: "incidents et SLA",
  zabbix: "mesures et alertes",
  centreon: "mesures et alertes",
  netxms: "états, alertes et liens",
  nagios: "états et alertes",
  nsp: "états et alertes",
};

/** Un outil configuré qui ne fournit pas de données fraîches. */
export function isFailing(tool) {
  if (!tool || tool.not_configured) return false;
  return Boolean(tool.never_collected || !tool.reachable || tool.stale || tool.data_until);
}

/** Outils en erreur parmi ceux dont dépend un indicateur. */
export function failingFor(tools, dependency) {
  const wanted = Array.isArray(dependency)
    ? dependency
    : SOURCE_DEPENDENCIES[dependency] ?? [dependency];
  return (tools ?? []).filter((tool) => wanted.includes(tool.tool) && isFailing(tool));
}

/** « Zabbix, iTop » */
export function toolNames(tools) {
  return tools.map((tool) => toolLabel(tool.tool)).join(", ");
}

/** « 2 sources en erreur : Zabbix, iTop → mesures et alertes, incidents et SLA incomplets » */
export function sourcesSentence(tools) {
  const failing = (tools ?? []).filter(isFailing);
  if (!failing.length) return null;
  const impacts = [...new Set(failing.map((tool) => IMPACT[tool.tool]).filter(Boolean))];
  return `${failing.length} source(s) en erreur ou à l'arrêt : ${toolNames(failing)}${
    impacts.length ? ` → ${impacts.join(", ")} incomplets` : ""
  }`;
}

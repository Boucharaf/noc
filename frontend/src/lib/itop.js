/**
 * Vocabulaire des tickets iTop (modèle ITIL standard : Incident et
 * UserRequest), et des états d'engagement calculés par le backend
 * (app/services/incident_service.py::_sla_state).
 */
export const ITOP_STATUS = {
  new: { label: "Nouveau", color: "var(--sev-high)" },
  assigned: { label: "Affecté", color: "var(--accent-ink)" },
  pending: { label: "En attente", color: "var(--sev-medium)" },
  escalated_tto: { label: "Escaladé (prise en charge)", color: "var(--sev-critical)" },
  escalated_ttr: { label: "Escaladé (résolution)", color: "var(--sev-critical)" },
  waiting_for_approval: { label: "Attente d'approbation", color: "var(--sev-medium)" },
  approved: { label: "Approuvé", color: "var(--accent-ink)" },
  resolved: { label: "Résolu", color: "var(--state-up)" },
  closed: { label: "Clos", color: "var(--ink-3)" },
  rejected: { label: "Rejeté", color: "var(--ink-3)" },
};

export const itopStatusMeta = (status) =>
  ITOP_STATUS[status] ?? { label: status ?? "—", color: "var(--ink-3)" };

/** Statuts d'un changement iTop (modèle ITIL standard). */
export const CHANGE_STATUS = {
  new: { label: "Nouveau", color: "var(--ink-2)" },
  validated: { label: "Validé", color: "var(--accent-ink)" },
  assigned: { label: "Affecté", color: "var(--accent-ink)" },
  plannedscheduled: { label: "Planifié", color: "var(--accent-ink)" },
  approved: { label: "Approuvé", color: "var(--state-up)" },
  implemented: { label: "Mis en œuvre", color: "var(--state-maintenance)" },
  monitored: { label: "En observation", color: "var(--state-maintenance)" },
  closed: { label: "Clos", color: "var(--ink-3)" },
};

export const changeStatusMeta = (status) =>
  CHANGE_STATUS[status] ?? { label: status ?? "—", color: "var(--ink-3)" };

export const SLA_STATUS = {
  met: { label: "Tenu", color: "var(--state-up)" },
  breached: { label: "Dépassé", color: "var(--sev-critical)" },
  running: { label: "Dans les délais", color: "var(--accent-ink)" },
  no_target: { label: "Sans objectif", color: "var(--ink-3)" },
};

export const slaStatusMeta = (status) => SLA_STATUS[status] ?? SLA_STATUS.no_target;

export const ITOP_PRIORITY = { 1: "P1 · critique", 2: "P2 · haute", 3: "P3 · moyenne", 4: "P4 · basse" };

export const priorityLabel = (priority) => ITOP_PRIORITY[priority] ?? (priority ? `P${priority}` : "—");

/** Codes de résolution iTop (UserRequest / Incident ITIL) : la cause retenue à la clôture. */
export const RESOLUTION_CODE = {
  assistance: "Assistance",
  "bug fixed": "Correction d'anomalie",
  "hardware repair": "Réparation matérielle",
  other: "Autre",
  "software patch": "Correctif logiciel",
  "system update": "Mise à jour système",
  training: "Formation",
};

export const resolutionCodeLabel = (code) => RESOLUTION_CODE[code] ?? code ?? "—";

/** Couleur d'un taux de respect des SLA (objectif 95 %). */
export function complianceColor(value) {
  if (value == null) return "var(--ink-3)";
  if (value >= 95) return "var(--state-up)";
  if (value >= 85) return "var(--sev-medium)";
  return "var(--sev-critical)";
}

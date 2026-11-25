import {
  AlertTriangle,
  CheckCircle2,
  CircleHelp,
  Info,
  OctagonAlert,
  PowerOff,
  Wrench,
  XCircle,
} from "lucide-react";

import {
  fieldStatusMeta,
  nodeStateMeta,
  severityMeta,
  statusMeta,
  toolLabel,
  toolStateMeta,
} from "../../lib/vocabulary";

/**
 * Pastilles de statut.
 *
 * Toutes construites sur le même moule : un fond très peu saturé
 * (`color-mix` à 14 %) et un texte à pleine couleur. Un badge en aplat
 * plein attire autant l'œil qu'une alerte critique, ce qui ruine la
 * hiérarchie visuelle dès qu'il y en a douze dans un tableau.
 */
export function Badge({ color = "var(--ink-3)", children, title, className = "", icon: Icon }) {
  return (
    <span
      className={`badge ${className}`}
      title={title}
      style={{
        color,
        background: `color-mix(in srgb, ${color} 14%, transparent)`,
        borderColor: `color-mix(in srgb, ${color} 32%, transparent)`,
        gap: Icon ? 3 : undefined,
      }}
    >
      {Icon && <Icon size={11} strokeWidth={2.2} aria-hidden="true" className="shrink-0" />}
      {children}
    </span>
  );
}

// AM-05 : chaque statut a une ICÔNE en plus de sa couleur et de son libellé,
// pour rester lisible par un daltonien et sur un écran mal calibré.
const STATE_ICON = {
  up: CheckCircle2,
  degraded: AlertTriangle,
  down: XCircle,
  unknown: CircleHelp,
  silent: CircleHelp,
  maintenance: Wrench,
  inactive: PowerOff,
};

const SEVERITY_ICON = {
  critical: OctagonAlert,
  high: AlertTriangle,
  medium: AlertTriangle,
  low: Info,
  info: Info,
  unknown: CircleHelp,
};

/**
 * Gravité. Pour une alerte d'outil, `source` porte la gravité D'ORIGINE en
 * clair (« Désastre », « Majeure », « Hôte injoignable ») : c'est elle qui
 * s'affiche ; la couleur suit l'échelle commune du NOC, pour que les outils
 * restent comparables.
 */
export function SeverityBadge({ severity, short = false, source, tool }) {
  const meta = severityMeta(severity);
  if (source) {
    return (
      <Badge
        color={meta.color}
        icon={SEVERITY_ICON[severity] ?? CircleHelp}
        title={`Gravité ${tool ? `${toolLabel(tool)} ` : "d'origine "}: ${source} — niveau commun : ${meta.label}`}
      >
        {source}
      </Badge>
    );
  }
  return (
    <Badge color={meta.color} icon={SEVERITY_ICON[severity] ?? CircleHelp} title={`Gravité : ${meta.label}`}>
      {short ? meta.short : meta.label}
    </Badge>
  );
}

export function StatusBadge({ status }) {
  const meta = statusMeta(status);
  return <Badge color={meta.color}>{meta.label}</Badge>;
}

export function NodeStateBadge({ state }) {
  const meta = nodeStateMeta(state);
  return (
    <Badge color={meta.color} icon={STATE_ICON[state] ?? CircleHelp} title={meta.hint}>
      {meta.label}
    </Badge>
  );
}

export function FieldStatusBadge({ status }) {
  const meta = fieldStatusMeta(status);
  return <Badge color={meta.color}>{meta.label}</Badge>;
}

export function ToolStateBadge({ state }) {
  const meta = toolStateMeta(state);
  return <Badge color={meta.color}>{meta.label}</Badge>;
}

/** Nom d'outil source, en encre discrète — c'est un contexte, pas un état. */
export function ToolTag({ tool }) {
  if (!tool) return <span style={{ color: "var(--ink-3)" }}>—</span>;
  return (
    <span className="mono-xs" style={{ color: "var(--ink-3)" }} title="Outil source">
      {toolLabel(tool)}
    </span>
  );
}

/**
 * Point d'état seul, sans texte : utilisé dans les tableaux denses où le
 * libellé serait redondant avec la colonne voisine.
 */
export function StateDot({ state, size = 8, pulse = false }) {
  const meta = nodeStateMeta(state);
  return (
    <span
      className={`dot ${pulse ? "blink-critical" : ""}`}
      title={`${meta.label} — ${meta.hint}`}
      style={{ background: meta.color, width: size, height: size }}
    />
  );
}

export function SeverityDot({ severity, pulse = false, size = 8 }) {
  const meta = severityMeta(severity);
  return (
    <span
      className={`dot ${pulse ? "blink-critical" : ""}`}
      title={meta.label}
      style={{ background: meta.color, width: size, height: size }}
    />
  );
}

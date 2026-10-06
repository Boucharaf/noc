import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";

import { DASH } from "../../lib/format";

/**
 * Tuile d'indicateur.
 *
 * Trois règles tenues partout :
 *
 * 1. La valeur domine (20 px, chasse fixe tabulaire), le libellé est
 *    secondaire. Un exploitant lit la colonne de chiffres en balayage
 *    vertical ; des libellés aussi gros que les valeurs cassent ce
 *    balayage.
 * 2. Une cible (`target`) est affichée telle quelle, sous la valeur —
 *    un KPI sans son seuil n'est pas interprétable : « MTTR 5 h 20 » ne
 *    dit rien tant qu'on ne sait pas que l'objectif est 4 h.
 * 3. La variation est colorée selon son SENS MÉTIER, pas son signe
 *    (`invertDelta` pour les indicateurs où monter est mauvais). Un
 *    « +12 incidents » en vert est une faute d'interprétation garantie.
 */
export default function Stat({
  label,
  value,
  unit,
  hint,
  target,
  delta,
  deltaLabel,
  invertDelta = false,
  color,
  to,
  compact = false,
  status,
}) {
  const hasDelta = delta !== null && delta !== undefined && Number.isFinite(Number(delta));
  const numericDelta = hasDelta ? Number(delta) : 0;
  const improving = invertDelta ? numericDelta < 0 : numericDelta > 0;
  const flat = Math.abs(numericDelta) < 0.005;

  const deltaColor = flat
    ? "var(--ink-3)"
    : improving
      ? "var(--state-up)"
      : "var(--sev-high)";
  const DeltaIcon = flat ? ArrowRight : numericDelta > 0 ? ArrowUpRight : ArrowDownRight;

  const body = (
    <>
      <div className="flex items-center gap-1.5">
        <span
          className="text-[10.5px] font-semibold uppercase tracking-[0.07em] truncate"
          style={{ color: "var(--ink-3)" }}
        >
          {label}
        </span>
        {status && (
          <span
            className="dot"
            style={{ background: status, width: 6, height: 6 }}
            aria-hidden="true"
          />
        )}
      </div>

      <div className="flex items-baseline gap-1 mt-0.5">
        <span
          className="num font-semibold leading-none"
          style={{ fontSize: compact ? 17 : 21, color: color ?? "var(--ink)" }}
        >
          {value ?? DASH}
        </span>
        {unit && (
          <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
            {unit}
          </span>
        )}
      </div>

      {(target || hasDelta || hint) && (
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {target && (
            <span className="text-[10.5px] num" style={{ color: "var(--ink-3)" }}>
              cible {target}
            </span>
          )}
          {hasDelta && (
            <span
              className="text-[10.5px] num inline-flex items-center gap-0.5"
              style={{ color: deltaColor }}
              title={deltaLabel ?? "Variation vs mois précédent"}
            >
              <DeltaIcon size={10} />
              {Math.abs(numericDelta).toLocaleString("fr-FR", {
                maximumFractionDigits: 2,
              })}
            </span>
          )}
          {hint && (
            <span className="text-[10.5px] truncate" style={{ color: "var(--ink-3)" }}>
              {hint}
            </span>
          )}
        </div>
      )}
    </>
  );

  const className = `panel px-2.5 ${compact ? "py-1.5" : "py-2"} block ${
    to ? "hover:border-[var(--border-strong)] transition-colors" : ""
  }`;

  return to ? (
    <Link to={to} className={className} style={{ textDecoration: "none", color: "inherit" }}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

/**
 * Barre de mesure horizontale — utilisée pour CPU/RAM/couverture.
 * Le remplissage est plafonné à 100 % mais la valeur affichée ne l'est
 * pas : masquer un CPU à 140 % (relevé aberrant d'un agent) ferait
 * disparaître exactement le signal qu'on veut voir.
 */
export function Meter({ value, max = 100, color = "var(--accent)", height = 4, track }) {
  const ratio = value === null || value === undefined ? 0 : Math.min(1, Math.max(0, value / max));
  return (
    <div
      className="w-full rounded-full overflow-hidden"
      style={{ height, background: track ?? "var(--surface-3)" }}
    >
      <div
        style={{
          width: `${ratio * 100}%`,
          height: "100%",
          background: color,
          transition: "width .3s ease",
        }}
      />
    </div>
  );
}

/**
 * Répartition en une seule barre segmentée.
 * Préférée à quatre barres empilées pour les compteurs de gravité :
 * l'information utile est la PROPORTION de critique dans le total, et
 * elle se lit d'un coup d'œil sur une barre unique.
 */
export function StackedBar({ segments, height = 6, title }) {
  const total = segments.reduce((sum, segment) => sum + (segment.value || 0), 0);
  if (!total) {
    return (
      <div
        className="w-full rounded-full"
        style={{ height, background: "var(--surface-3)" }}
        title={title}
      />
    );
  }
  return (
    <div className="w-full rounded-full overflow-hidden flex" style={{ height }} title={title}>
      {segments.map((segment) => (
        <div
          key={segment.key}
          style={{
            width: `${((segment.value || 0) / total) * 100}%`,
            background: segment.color,
          }}
          title={`${segment.label} : ${segment.value}`}
        />
      ))}
    </div>
  );
}

/** Ligne libellé / valeur, pour les fiches de détail. */
export function DefRow({ label, children, mono = false }) {
  return (
    <div className="flex items-baseline gap-2 py-[3px]">
      <span
        className="text-[10.5px] uppercase tracking-[0.06em] shrink-0"
        style={{ color: "var(--ink-3)", minWidth: 108 }}
      >
        {label}
      </span>
      <span className={`text-[12.5px] min-w-0 ${mono ? "num" : ""}`}>{children ?? DASH}</span>
    </div>
  );
}

import { ArrowDownRight, ArrowRight, ArrowUpRight, HelpCircle } from "lucide-react";
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
 *
 * Représentations facultatives, pour comprendre sans lire :
 *   `gauge`     { value, target, max, higherIsBetter, color } — jauge avec
 *               un repère d'objectif : l'écart à la cible se voit ;
 *   `spark`     valeurs des dernières 24 h — mini-courbe, avec une flèche
 *               de tendance si `delta` n'est pas fourni ;
 *   `breakdown` segments { key, label, value, color } — barre de
 *               répartition, le « pourquoi » d'un chiffre ;
 *   `help`      définition affichée au survol du « ? ».
 */
function Gauge({ value, target, max = 100, color = "var(--accent)" }) {
  const clamp = (v) => Math.min(100, Math.max(0, (100 * v) / max));
  const filled = value == null || !Number.isFinite(Number(value)) ? 0 : clamp(Number(value));
  return (
    <div className="relative mt-1.5" style={{ height: 6 }} aria-hidden="true">
      <div className="absolute inset-0 rounded-full" style={{ background: "var(--surface-3)" }} />
      <div
        className="absolute left-0 top-0 bottom-0 rounded-full"
        style={{ width: `${filled}%`, background: color, transition: "width .3s ease" }}
      />
      {target != null && (
        <div
          className="absolute"
          style={{
            left: `calc(${clamp(target)}% - 1px)`,
            top: -3,
            bottom: -3,
            width: 2,
            background: "var(--ink)",
            borderRadius: 1,
          }}
          title={`Objectif : ${target}`}
        />
      )}
    </div>
  );
}

function MiniSpark({ values, color }) {
  const points = (values ?? []).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  if (points.length < 2) return null;
  const width = 64;
  const height = 20;
  // Échelle verticale d'au moins 5 % de la valeur (et d'une unité) :
  // ramenée à son propre min/max, une variation de 69,6 à 69,7 % dessinerait
  // une envolée. Seul un changement notable doit se voir.
  const low = Math.min(...points);
  const high = Math.max(...points);
  const span = Math.max(high - low, Math.abs(high) * 0.05, 1);
  const min = (low + high) / 2 - span / 2;
  const coords = points.map((v, i) => [
    (i / (points.length - 1)) * width,
    height - 2 - ((v - min) / span) * (height - 4),
  ]);
  const line = coords.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="shrink-0" aria-hidden="true">
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={color} opacity="0.12" />
      <path d={line} fill="none" stroke={color} strokeWidth="1.3" strokeLinejoin="round" />
      <circle cx={coords.at(-1)[0]} cy={coords.at(-1)[1]} r="1.8" fill={color} />
    </svg>
  );
}

function sparkDelta(values) {
  const points = (values ?? []).filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  return points.length >= 2 ? points.at(-1) - points[0] : null;
}

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
  gauge,
  spark,
  breakdown,
  help,
}) {
  if ((delta === null || delta === undefined) && spark) {
    delta = sparkDelta(spark);
    deltaLabel = deltaLabel ?? "Variation sur 24 h";
  }
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
      <div className="flex min-w-0 items-start gap-1.5">
        <span
          className="min-w-0 text-[10.5px] font-semibold uppercase leading-tight tracking-[0.07em] break-words"
          style={{ color: "var(--ink-3)", overflowWrap: "anywhere" }}
        >
          {label}
        </span>
        {help && (
          <span className="shrink-0 cursor-help" title={help} style={{ color: "var(--ink-3)" }}>
            <HelpCircle size={11} aria-label={help} />
          </span>
        )}
        {status && (
          <span
            className="dot"
            style={{ background: status, width: 6, height: 6 }}
            aria-hidden="true"
          />
        )}
      </div>

      <div className="flex min-w-0 flex-wrap items-baseline gap-1 mt-0.5">
        <span
          className="num min-w-0 font-semibold leading-tight break-words"
          style={{
            fontSize: compact ? 17 : 21,
            color: color ?? "var(--ink)",
            overflowWrap: "anywhere",
          }}
        >
          {value ?? DASH}
        </span>
        {unit && (
          <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
            {unit}
          </span>
        )}
        {spark && (
          <span className="ml-auto self-center">
            <MiniSpark values={spark} color={color ?? "var(--accent)"} />
          </span>
        )}
      </div>

      {gauge && <Gauge {...gauge} color={gauge.color ?? color ?? "var(--accent)"} />}
      {breakdown && (
        <div className="mt-1.5">
          <StackedBar segments={breakdown} height={5} />
        </div>
      )}

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
            <span
              className="text-[10.5px] break-words"
              style={{ color: "var(--ink-3)", overflowWrap: "anywhere" }}
            >
              {hint}
            </span>
          )}
        </div>
      )}
    </>
  );

  const className = `panel min-w-0 px-2.5 ${compact ? "py-1.5" : "py-2"} block ${
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

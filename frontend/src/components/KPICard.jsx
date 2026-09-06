import React from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { STATUS } from "../theme/colors";

const SENTIMENT_COLOR = {
  good: STATUS.good,
  bad: STATUS.critical,
  neutral: "var(--color-text-secondary)",
};

/**
 * `trendDirection` ('up' | 'down') controls the arrow — it must reflect the
 * actual sign of the change. `sentiment` ('good' | 'bad' | 'neutral') controls
 * the color, independently: e.g. incidents going up is trendDirection="up" but
 * sentiment="bad", so the up-arrow renders in red, not green.
 *
 * `size="hero"` is for the one or two figures a role's landing screen is
 * actually built around (disponibilité globale, incidents critiques) — a
 * bigger readout, unit set apart, no icon chip competing for attention.
 */
const KPICard = ({
  title,
  value,
  unit,
  icon: Icon,
  trend,
  trendDirection,
  sentiment = "neutral",
  loading,
  size = "normal",
  accent,
}) => {
  const color = SENTIMENT_COLOR[sentiment] ?? SENTIMENT_COLOR.neutral;
  const TrendIcon =
    trendDirection === "up"
      ? ArrowUpRight
      : trendDirection === "down"
        ? ArrowDownRight
        : Minus;
  const isHero = size === "hero";

  return (
    <div
      className="noc-panel flex flex-col justify-between p-4"
      style={accent ? { "--panel-accent": accent } : undefined}
    >
      <div className="mb-2 flex items-center justify-between">
        <h3
          className="text-xs font-medium"
          style={{ color: "var(--color-text-secondary)" }}
        >
          {title}
        </h3>
        {Icon && (
          <Icon
            className="h-4 w-4 shrink-0"
            style={{ color: "var(--color-text-muted)" }}
          />
        )}
      </div>
      <div
        className={`font-bold tabular-nums leading-none ${isHero ? "text-4xl" : "text-2xl"}`}
        style={{
          color: loading ? "var(--color-text-muted)" : "var(--color-text-primary)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {loading ? "—" : value}
        {unit && !loading && (
          <span
            className={isHero ? "ml-1 text-base font-medium" : "ml-0.5 text-sm font-medium"}
            style={{ color: "var(--color-text-secondary)", fontFamily: "inherit" }}
          >
            {unit}
          </span>
        )}
      </div>
      {trend != null && (
        <div
          className="mt-2 flex items-center gap-1 text-xs font-medium"
          style={{ color }}
        >
          <TrendIcon className="h-3.5 w-3.5" />
          <span>{trend}</span>
          <span
            className="font-normal"
            style={{ color: "var(--color-text-muted)" }}
          >
            vs mois dernier
          </span>
        </div>
      )}
    </div>
  );
};

export default KPICard;

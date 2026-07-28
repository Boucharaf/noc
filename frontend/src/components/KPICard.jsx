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
 */
const KPICard = ({
  title,
  value,
  icon: Icon,
  trend,
  trendDirection,
  sentiment = "neutral",
  loading,
}) => {
  const color = SENTIMENT_COLOR[sentiment] ?? SENTIMENT_COLOR.neutral;
  const TrendIcon =
    trendDirection === "up"
      ? ArrowUpRight
      : trendDirection === "down"
        ? ArrowDownRight
        : Minus;

  return (
    <div
      className="flex flex-col rounded-xl border p-4 transition-transform hover:-translate-y-0.5"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
        boxShadow: "var(--shadow-elevate)",
      }}
    >
      <div className="mb-1.5 flex items-center justify-between">
        <h3
          className="text-xs font-semibold uppercase tracking-wide"
          style={{ color: "var(--color-text-secondary)" }}
        >
          {title}
        </h3>
        {Icon && (
          <div
            className="rounded-md p-1.5"
            style={{ background: "var(--color-accent-soft)" }}
          >
            <Icon
              className="h-4 w-4"
              style={{ color: "var(--color-accent)" }}
            />
          </div>
        )}
      </div>
      <div
        className="text-2xl font-bold tabular-nums"
        style={{
          color: loading
            ? "var(--color-text-muted)"
            : "var(--color-text-primary)",
        }}
      >
        {loading ? "—" : value}
      </div>
      {trend != null && (
        <div
          className="mt-1.5 flex items-center gap-1 text-sm font-medium"
          style={{ color }}
        >
          <TrendIcon className="h-4 w-4" />
          <span>{trend}</span>
          <span
            className="font-normal"
            style={{ color: "var(--color-text-muted)" }}
          >
            vs. mois dernier
          </span>
        </div>
      )}
    </div>
  );
};

export default KPICard;

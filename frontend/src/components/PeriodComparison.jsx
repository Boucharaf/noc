import React from "react";
import { ArrowDownRight, ArrowUpRight, GitCompareArrows, Minus } from "lucide-react";
import Card from "./Card";
import { useKpiCompare } from "../hooks/useKPI";
import { STATUS } from "../theme/colors";

// upIsGood: whether an increase of the metric is a good thing (colors the delta)
const METRICS = [
  { key: "total_incidents", label: "Incidents", upIsGood: false, unit: "" },
  { key: "network_availability_pct", label: "Disponibilité", upIsGood: true, unit: "%" },
  { key: "resolution_rate_pct", label: "Taux de résolution", upIsGood: true, unit: "%" },
  { key: "avg_mttr_minutes", label: "MTTR moyen", upIsGood: false, unit: " min" },
];

const DeltaChip = ({ delta, upIsGood, unit }) => {
  if (delta == null) return null;
  const direction = delta > 0 ? "up" : delta < 0 ? "down" : "flat";
  const good = delta === 0 ? null : (delta > 0) === upIsGood;
  const color =
    good == null
      ? "var(--color-text-secondary)"
      : good
        ? STATUS.good
        : STATUS.critical;
  const Icon =
    direction === "up" ? ArrowUpRight : direction === "down" ? ArrowDownRight : Minus;
  return (
    <span
      className="inline-flex items-center gap-0.5 text-xs font-semibold tabular-nums"
      style={{ color }}
    >
      <Icon className="h-3.5 w-3.5" />
      {delta > 0 ? "+" : ""}
      {delta}
      {unit}
    </span>
  );
};

const PeriodComparison = () => {
  const { data, isLoading } = useKpiCompare();
  const comparisons = data?.comparisons ?? [];

  return (
    <Card
      icon={GitCompareArrows}
      title="Comparaison de Périodes"
      subtitle={
        data
          ? `${data.period.label} vs N-1 et N-3 mois`
          : "N vs N-1 et N-3 mois"
      }
    >
      {isLoading ? (
        <div
          className="flex h-40 items-center justify-center text-sm"
          style={{ color: "var(--color-text-muted)" }}
        >
          Chargement…
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[540px] text-sm">
            <thead>
              <tr
                className="text-left text-xs uppercase tracking-wide"
                style={{ color: "var(--color-text-secondary)" }}
              >
                <th className="whitespace-nowrap py-2 pr-4 font-semibold">
                  Indicateur
                </th>
                <th className="whitespace-nowrap py-2 pr-4 font-semibold tabular-nums">
                  {data?.period.label}
                </th>
                {comparisons.map((c) => (
                  <th
                    key={c.offset_months}
                    className="whitespace-nowrap py-2 pr-4 font-semibold"
                  >
                    N-{c.offset_months} ({c.period.label})
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRICS.map(({ key, label, upIsGood, unit }) => (
                <tr
                  key={key}
                  className="border-t"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  <td
                    className="whitespace-nowrap py-1.5 pr-4 font-medium"
                    style={{ color: "var(--color-text-primary)" }}
                  >
                    {label}
                  </td>
                  <td
                    className="py-1.5 pr-4 font-bold tabular-nums"
                    style={{ color: "var(--color-text-primary)" }}
                  >
                    {data?.kpi[key]}
                    {unit}
                  </td>
                  {comparisons.map((c) => (
                    <td
                      key={c.offset_months}
                      className="whitespace-nowrap py-1.5 pr-4"
                    >
                      <span
                        className="mr-2 tabular-nums"
                        style={{ color: "var(--color-text-secondary)" }}
                      >
                        {c.kpi[key]}
                        {unit}
                      </span>
                      <DeltaChip
                        delta={c.deltas[key]}
                        upIsGood={upIsGood}
                        unit={unit}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
};

export default PeriodComparison;

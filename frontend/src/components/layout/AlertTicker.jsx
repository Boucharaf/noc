import React from "react";
import { useOpenAlerts } from "../../hooks/useRealtime";
import { formatAge } from "../../utils/format";
import { SEVERITY_COLOR } from "../../theme/colors";

/**
 * A continuous marquee of the currently-open critical/high incidents — the
 * "bandeau dernière alerte en temps réel" the KPI document asks for. Renders
 * nothing when the feed is empty or still loading: an empty ticker bar is
 * worse than no bar, it reads as a broken widget rather than a quiet network.
 */
const AlertTicker = () => {
  const { data: alerts = [] } = useOpenAlerts(15);
  const urgent = alerts.filter((a) => a.severity === "critical" || a.severity === "high");

  if (urgent.length === 0) return null;

  // Duplicated once so the marquee loops seamlessly (see .noc-ticker-track,
  // which scrolls by exactly -50% of its own width).
  const track = [...urgent, ...urgent];

  return (
    <div
      className="flex h-8 shrink-0 items-center gap-3 overflow-hidden border-b px-3"
      style={{ background: "var(--color-signal-soft)", borderColor: "var(--color-border)" }}
    >
      <span className="flex shrink-0 items-center gap-1.5 text-[11px] font-semibold" style={{ color: "var(--color-signal)" }}>
        <span className="noc-live-dot" />
        ALERTES
      </span>
      <div className="min-w-0 flex-1 overflow-hidden">
        <div className="noc-ticker-track" style={{ animationDuration: `${urgent.length * 6}s` }}>
          {track.map((alert, i) => (
            <span
              key={`${alert.id}-${i}`}
              className="flex shrink-0 items-center gap-1.5 whitespace-nowrap px-4 text-xs"
              style={{ color: "var(--color-text-primary)" }}
            >
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ background: SEVERITY_COLOR[alert.severity] }}
              />
              <span className="font-mono" style={{ color: "var(--color-text-secondary)" }}>
                [{alert.node_code}]
              </span>
              {alert.description ?? "Incident sans description"}
              <span style={{ color: "var(--color-text-muted)" }}>· {alert.locality} · {formatAge(alert.age_minutes)}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

export default AlertTicker;

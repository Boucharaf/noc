import React from "react";
import { Bell, Check, Ticket } from "lucide-react";
import Card from "./Card";
import { useAcknowledgeIncident, useOpenAlerts } from "../hooks/useRealtime";
import { useAuthStore } from "../store/auth";
import { SEVERITY_COLOR } from "../theme/colors";

const formatAge = (minutes) => {
  if (minutes < 60) return `il y a ${minutes} min`;
  if (minutes < 1440) return `il y a ${Math.round(minutes / 60)}h`;
  return `il y a ${Math.round(minutes / 1440)}j`;
};

const AlertFeed = () => {
  const { data: alerts = [], isLoading } = useOpenAlerts(20);
  const acknowledge = useAcknowledgeIncident();
  const role = useAuthStore((state) => state.user?.role);
  // Spec §10.1 — analysts are read-only; the backend enforces this with a 403,
  // so don't show them an action that can only fail.
  const canAcknowledge = role === "admin" || role === "noc_agent";

  return (
    <Card
      icon={Bell}
      title="Flux d'Alertes en Direct"
      subtitle="Actualisation automatique toutes les 15s"
      action={
        <span
          className="rounded-full px-2 py-0.5 text-xs font-semibold"
          style={{
            background: "var(--color-accent-soft)",
            color: "var(--color-accent)",
          }}
        >
          {alerts.length} ouverte(s)
        </span>
      }
      bodyClassName="p-3 overflow-y-auto"
      bodyStyle={{ maxHeight: "clamp(280px, calc(100vh - 480px), 640px)" }}
    >
      <div className="space-y-1">
        {isLoading && (
          <p
            className="p-2 text-sm"
            style={{ color: "var(--color-text-muted)" }}
          >
            Chargement…
          </p>
        )}
        {!isLoading && alerts.length === 0 && (
          <p
            className="p-2 text-sm"
            style={{ color: "var(--color-text-muted)" }}
          >
            Aucune alerte ouverte.
          </p>
        )}
        {alerts.map((alert) => {
          const color = SEVERITY_COLOR[alert.severity] ?? SEVERITY_COLOR.low;
          return (
            <div
              key={alert.id}
              className="flex items-start gap-3 rounded-lg py-2 pl-3 pr-2 transition-colors hover:bg-[var(--color-surface-2)]"
              style={{ borderLeft: `3px solid ${color}` }}
            >
              <div className="min-w-0 flex-1">
                <p
                  className="truncate text-sm font-medium"
                  style={{ color: "var(--color-text-primary)" }}
                >
                  <span className="font-mono text-xs" style={{ color }}>
                    [{alert.node_code}]
                  </span>{" "}
                  {alert.description ?? "Incident sans description"}
                </p>
                <p
                  className="text-xs"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {alert.locality} — {formatAge(alert.age_minutes)}
                  {alert.itop_ticket_id && (
                    <span
                      className="ml-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono"
                      style={{
                        background: "var(--color-accent-soft)",
                        color: "var(--color-accent)",
                      }}
                    >
                      <Ticket className="h-3 w-3" />
                      {alert.itop_ticket_id}
                    </span>
                  )}
                </p>
              </div>
              {canAcknowledge && alert.status === "open" && (
                <button
                  onClick={() => acknowledge.mutate(alert.id)}
                  disabled={acknowledge.isPending}
                  title="Prendre en charge"
                  className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-[var(--color-surface-3)]"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  <Check className="h-4 w-4" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
};

export default AlertFeed;

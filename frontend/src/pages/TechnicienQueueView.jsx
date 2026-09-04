import React, { useState } from "react";
import { CheckCircle2, ListChecks, Ticket } from "lucide-react";
import Card from "../components/Card";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import { useAcknowledgeIncident, useOpenAlerts, useResolveIncident } from "../hooks/useRealtime";
import { useHasPermission } from "../hooks/usePermission";
import { PERMISSIONS } from "../api/permissions";
import { formatAge } from "../utils/format";

// File de travail Technicien : l'écran opérationnel qui manquait à ce rôle —
// contrairement au Chef NOC/Directeur, il n'a pas besoin d'une vue globale
// KPI, il a besoin de savoir "qu'est-ce qui m'attend là, maintenant".
const ResolveForm = ({ incidentId, onDone }) => {
  const [notes, setNotes] = useState("");
  const resolve = useResolveIncident();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        resolve.mutate(
          { id: incidentId, notes },
          { onSuccess: () => onDone?.() }
        );
      }}
      className="mt-2 flex items-center gap-2"
    >
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder="Note de résolution (obligatoire)"
        className="flex-1 rounded-md border px-2.5 py-1.5 text-xs outline-none"
        style={{ borderColor: "var(--color-border-strong)", background: "var(--color-surface-2)", color: "var(--color-text-primary)" }}
      />
      <button
        type="submit"
        disabled={!notes.trim() || resolve.isPending}
        className="shrink-0 rounded-md px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
        style={{ background: "var(--color-accent)" }}
      >
        Résoudre
      </button>
    </form>
  );
};

const TechnicienQueueView = () => {
  const { data: alerts = [], isLoading } = useOpenAlerts(50);
  const acknowledge = useAcknowledgeIncident();
  const canResolve = useHasPermission(PERMISSIONS.RESOLVE_INCIDENT);
  const [resolvingId, setResolvingId] = useState(null);

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div className="flex items-center gap-2">
        <ListChecks className="h-5 w-5" style={{ color: "var(--color-accent)" }} />
        <div>
          <h1 className="text-lg font-bold" style={{ color: "var(--color-text-primary)" }}>
            Mes alertes
          </h1>
          <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
            Incidents ouverts ou acquittés, du plus ancien au plus récent.
          </p>
        </div>
      </div>

      {isLoading && (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Chargement…</p>
      )}
      {!isLoading && alerts.length === 0 && (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Aucune alerte ouverte.</p>
      )}

      <div className="space-y-2">
        {alerts.map((alert) => (
          <Card key={alert.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium" style={{ color: "var(--color-text-primary)" }}>
                  <span className="font-mono text-xs" style={{ color: "var(--color-text-secondary)" }}>
                    [{alert.node_code}]
                  </span>{" "}
                  {alert.description ?? "Incident sans description"}
                </p>
                <p className="mt-1 flex items-center gap-2 text-xs" style={{ color: "var(--color-text-secondary)" }}>
                  {alert.locality} · {formatAge(alert.age_minutes)}
                  {alert.itop_ticket_id && (
                    <span className="inline-flex items-center gap-1 font-mono">
                      <Ticket className="h-3 w-3" />
                      {alert.itop_ticket_id}
                    </span>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <SeverityBadge severity={alert.severity} />
                <StatusBadge status={alert.status} />
              </div>
            </div>

            <div className="mt-3 flex items-center gap-2">
              {alert.status === "open" && (
                <button
                  onClick={() => acknowledge.mutate(alert.id)}
                  disabled={acknowledge.isPending}
                  className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
                  style={{ borderColor: "var(--color-border-strong)", color: "var(--color-text-primary)" }}
                >
                  <CheckCircle2 className="h-3.5 w-3.5" />
                  Prendre en charge
                </button>
              )}
              {canResolve && alert.status === "acknowledged" && resolvingId !== alert.id && (
                <button
                  onClick={() => setResolvingId(alert.id)}
                  className="rounded-md px-3 py-1.5 text-xs font-semibold text-white"
                  style={{ background: "var(--color-accent)" }}
                >
                  Clôturer
                </button>
              )}
            </div>

            {canResolve && resolvingId === alert.id && (
              <ResolveForm incidentId={alert.id} onDone={() => setResolvingId(null)} />
            )}
          </Card>
        ))}
      </div>
    </div>
  );
};

export default TechnicienQueueView;

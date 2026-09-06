import React, { useState } from "react";
import { Check, CheckCheck, Loader2 } from "lucide-react";
import { SeverityBadge, StatusBadge } from "./Badge";
import { STATUS } from "../theme/colors";

const formatDateTime = (iso) =>
  iso
    ? new Date(iso).toLocaleString("fr-FR", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      })
    : "—";

const ResolveDialog = ({ incident, onConfirm, onCancel, pending }) => {
  const [notes, setNotes] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        className="w-full max-w-md rounded-xl border p-4"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}
      >
        <h3 className="mb-1 text-sm font-semibold">Résoudre l'incident #{incident.id}</h3>
        <p className="mb-3 text-xs" style={{ color: "var(--color-text-secondary)" }}>
          {incident.node_name} ({incident.node_code}) — une note de résolution est obligatoire.
        </p>
        <textarea
          autoFocus
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder="Cause identifiée, action corrective effectuée…"
          className="mb-3 w-full rounded-md border p-2 text-sm outline-none"
          style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
        />
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm font-medium"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Annuler
          </button>
          <button
            onClick={() => notes.trim() && onConfirm(notes)}
            disabled={!notes.trim() || pending}
            className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
            style={{ background: STATUS.good }}
          >
            {pending ? "Résolution…" : "Confirmer la résolution"}
          </button>
        </div>
      </div>
    </div>
  );
};

/**
 * `compact` drops pagination/filters chrome for embedded use (e.g. the "Incidents
 * en cours" panel on the Chef NOC dashboard) — the parent still controls what
 * slice of data is passed in either mode.
 */
const IncidentQueueTable = ({
  incidents = [],
  total,
  page = 1,
  pageSize = 25,
  onPageChange,
  loading = false,
  canAcknowledge = false,
  canResolve = false,
  onAcknowledge,
  onResolve,
  acknowledgingId,
  resolvingId,
  onOpenNode,
  compact = false,
  emptyLabel = "Aucun incident.",
}) => {
  const [resolveTarget, setResolveTarget] = useState(null);
  const pages = pageSize ? Math.max(1, Math.ceil((total ?? incidents.length) / pageSize)) : 1;

  return (
    <>
      <div className={compact ? "" : "noc-panel"}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr
                className="border-b text-left text-xs font-medium"
                style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
              >
                <th className="whitespace-nowrap px-3 py-2">Nœud</th>
                <th className="whitespace-nowrap px-3 py-2">Sévérité</th>
                <th className="whitespace-nowrap px-3 py-2">Statut</th>
                <th className="px-3 py-2">Description</th>
                <th className="whitespace-nowrap px-3 py-2">Détecté</th>
                <th className="whitespace-nowrap px-3 py-2">Ticket</th>
                {(canAcknowledge || canResolve) && <th className="whitespace-nowrap px-3 py-2">Actions</th>}
              </tr>
            </thead>
            <tbody className="divide-y" style={{ borderColor: "var(--color-border)" }}>
              {loading && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
                    Chargement…
                  </td>
                </tr>
              )}
              {!loading && incidents.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>
                    {emptyLabel}
                  </td>
                </tr>
              )}
              {incidents.map((inc) => (
                <tr key={inc.id} className="transition-colors hover:bg-[var(--color-surface-2)]">
                  <td className="whitespace-nowrap px-3 py-2">
                    <button
                      onClick={() => onOpenNode?.(inc.node_code)}
                      className="text-left font-mono text-xs underline decoration-dotted"
                      style={{ color: "var(--color-accent)" }}
                      title={inc.node_name}
                    >
                      {inc.node_code}
                    </button>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2"><SeverityBadge severity={inc.severity} /></td>
                  <td className="whitespace-nowrap px-3 py-2"><StatusBadge status={inc.status} /></td>
                  <td className="max-w-xs truncate px-3 py-2" style={{ color: "var(--color-text-secondary)" }} title={inc.description}>
                    {inc.description || "—"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs" style={{ color: "var(--color-text-muted)" }}>
                    {formatDateTime(inc.detected_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs" style={{ color: "var(--color-text-secondary)" }}>
                    {inc.itop_ticket_id ?? "—"}
                  </td>
                  {(canAcknowledge || canResolve) && (
                    <td className="whitespace-nowrap px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        {canAcknowledge && inc.status === "open" && (
                          <button
                            onClick={() => onAcknowledge?.(inc.id)}
                            disabled={acknowledgingId === inc.id}
                            title="Acquitter"
                            className="rounded-md p-1.5 hover:bg-[var(--color-surface-3)]"
                            style={{ color: STATUS.warning }}
                          >
                            {acknowledgingId === inc.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                          </button>
                        )}
                        {canResolve && inc.status !== "resolved" && inc.status !== "closed" && (
                          <button
                            onClick={() => setResolveTarget(inc)}
                            disabled={resolvingId === inc.id}
                            title="Résoudre"
                            className="rounded-md p-1.5 hover:bg-[var(--color-surface-3)]"
                            style={{ color: STATUS.good }}
                          >
                            {resolvingId === inc.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCheck className="h-4 w-4" />}
                          </button>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!compact && onPageChange && pages > 1 && (
          <div
            className="flex items-center justify-between border-t px-3 py-2 text-xs"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}
          >
            <span>
              {total} incident(s) · page {page}/{pages}
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => onPageChange(Math.max(1, page - 1))}
                disabled={page <= 1}
                className="rounded-md border px-2 py-1 disabled:opacity-40"
                style={{ borderColor: "var(--color-border)" }}
              >
                Précédent
              </button>
              <button
                onClick={() => onPageChange(Math.min(pages, page + 1))}
                disabled={page >= pages}
                className="rounded-md border px-2 py-1 disabled:opacity-40"
                style={{ borderColor: "var(--color-border)" }}
              >
                Suivant
              </button>
            </div>
          </div>
        )}
      </div>

      {resolveTarget && (
        <ResolveDialog
          incident={resolveTarget}
          pending={resolvingId === resolveTarget.id}
          onCancel={() => setResolveTarget(null)}
          onConfirm={(notes) => {
            onResolve?.(resolveTarget.id, notes);
            setResolveTarget(null);
          }}
        />
      )}
    </>
  );
};

export default IncidentQueueTable;

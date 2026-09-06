import React from "react";
import { useQuery } from "@tanstack/react-query";
import { X, Server, AlertTriangle } from "lucide-react";
import apiClient from "../api/client";
import { listIncidents } from "../api/alerts";
import { usePeriodStore } from "../store";
import { SeverityBadge, StatusBadge } from "./Badge";
import { STATUS } from "../theme/colors";

// Pas d'endpoint /api/kpi/nodes/{code} : on retrouve le nœud dans le lot déjà
// exposé par /api/kpi/nodes (limit relevé pour maximiser les chances de
// l'y trouver plutôt que d'ajouter une route que le backend n'a pas).
const useNodeStats = (nodeCode, localityId) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ["kpi", "node-lookup", nodeCode, localityId, year, month],
    enabled: !!nodeCode,
    queryFn: async ({ signal }) => {
      const { data } = await apiClient.get("/kpi/nodes", {
        params: { month, year, locality_id: localityId ?? undefined, limit: 100 },
        signal,
      });
      return data.find((n) => n.code === nodeCode) ?? null;
    },
  });
};

const useNodeHistory = (nodeCode) =>
  useQuery({
    queryKey: ["incidents", "by-node", nodeCode],
    enabled: !!nodeCode,
    queryFn: ({ signal }) => listIncidents({ nodeCode, pageSize: 20 }, signal),
  });

const Stat = ({ label, value }) => (
  <div>
    <p className="text-[11px]" style={{ color: "var(--color-text-secondary)" }}>{label}</p>
    <p className="font-mono text-lg font-semibold tabular-nums" style={{ color: "var(--color-text-primary)" }}>{value}</p>
  </div>
);

const NodeDetailDrawer = ({ nodeCode, localityId, onClose }) => {
  const { data: node, isLoading: loadingNode } = useNodeStats(nodeCode, localityId);
  const { data: history, isLoading: loadingHistory } = useNodeHistory(nodeCode);

  if (!nodeCode) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40">
      <div
        className="flex h-full w-full max-w-lg flex-col border-l"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)" }}
      >
        <div className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: "var(--color-border)" }}>
          <div className="flex items-center gap-2 min-w-0">
            <Server className="h-4 w-4 shrink-0" style={{ color: "var(--color-accent)" }} />
            <div className="min-w-0">
              <h3 className="truncate font-mono text-sm font-semibold">{nodeCode}</h3>
              <p className="truncate text-xs" style={{ color: "var(--color-text-secondary)" }}>Vue technique — équipement</p>
            </div>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 hover:bg-[var(--color-surface-2)]">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {loadingNode && <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Chargement…</p>}

          {!loadingNode && !node && (
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
              Détails indisponibles pour cette période (aucune activité sur {nodeCode} ce mois-ci).
            </p>
          )}

          {node && (
            <>
              <div className="mb-4">
                <p className="text-sm font-semibold">{node.name}</p>
                <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
                  {node.locality} · outil : {node.source_tool}
                </p>
              </div>

              <div className="noc-panel mb-4 grid grid-cols-2 gap-4 p-4 sm:grid-cols-4" style={{ "--panel-accent": "var(--color-accent)" }}>
                <Stat label="Incidents (mois)" value={node.total_incidents} />
                <Stat label="Résolus" value={node.resolved} />
                <Stat label="MTTR moyen" value={node.avg_mttr != null ? `${Math.round(node.avg_mttr)} min` : "—"} />
                <Stat label="Disponibilité" value={node.availability_pct != null ? `${node.availability_pct}%` : "—"} />
              </div>

              <div
                className="mb-4 flex gap-2 rounded-md border p-3 text-xs"
                style={{ borderColor: STATUS.warning, background: "color-mix(in srgb, var(--color-page) 85%, transparent)" }}
              >
                <AlertTriangle className="h-4 w-4 shrink-0" style={{ color: STATUS.warning }} />
                <p style={{ color: "var(--color-text-secondary)" }}>
                  CPU, RAM, interface, trafic, latence par lien et logs bruts ne sont pas affichés ici :
                  le backend actuel n'expose que des KPI réseau agrégés (<code className="font-mono">/api/metrics/network</code>),
                  pas de métrique par équipement. Ajouter un endpoint dédié (ex. <code className="font-mono">GET /api/metrics/nodes/&#123;id&#125;</code>)
                  serait nécessaire pour compléter cette vue conformément au niveau 4 du document métier.
                </p>
              </div>
            </>
          )}

          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--color-text-secondary)" }}>
            Historique des incidents
          </h4>
          {loadingHistory && <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Chargement…</p>}
          {!loadingHistory && (history?.items?.length ?? 0) === 0 && (
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Aucun incident enregistré pour ce nœud.</p>
          )}
          <ul className="space-y-2">
            {history?.items?.map((inc) => (
              <li key={inc.id} className="rounded-md border p-2.5 text-sm" style={{ borderColor: "var(--color-border)" }}>
                <div className="mb-1 flex items-center gap-2">
                  <SeverityBadge severity={inc.severity} />
                  <StatusBadge status={inc.status} />
                  <span className="ml-auto font-mono text-xs" style={{ color: "var(--color-text-muted)" }}>
                    {new Date(inc.detected_at).toLocaleDateString("fr-FR")}
                  </span>
                </div>
                <p className="truncate" style={{ color: "var(--color-text-secondary)" }}>{inc.description || "—"}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default NodeDetailDrawer;

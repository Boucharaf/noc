import React, { useMemo, useState } from "react";
import { AlertCircle, ListChecks, MapPin, History, PlusCircle } from "lucide-react";
import Card from "../components/Card";
import KPICard from "../components/KPICard";
import AlertFeed from "../components/AlertFeed";
import IncidentQueueTable from "../components/IncidentQueueTable";
import NodeDetailDrawer from "../components/NodeDetailDrawer";
import ManualIncidentForm from "../components/ManualIncidentForm";
import { useOpenAlerts, useIncidentsList, useAcknowledgeIncident, useResolveIncident } from "../hooks/useRealtime";
import { useHasPermission } from "../hooks/usePermission";
import { PERMISSIONS } from "../api/permissions";
import { STATUS } from "../theme/colors";

const TABS = [
  { key: "a-traiter", label: "À traiter", statusFilter: "open" },
  { key: "en-charge", label: "Actions en cours", statusFilter: "acknowledged" },
  { key: "historique", label: "Historique", statusFilter: undefined },
];

/**
 * Niveau 3 du document métier : "Alertes temps réel | Incidents à traiter |
 * Sites affectés | Historique | Actions en cours" — le poste de travail
 * opérationnel, contrairement aux deux niveaux au-dessus qui sont des vues
 * de lecture. Toutes les actions ici passent par le rôle réel de
 * l'utilisateur connecté (technicien ou chef_noc) — pas de bouton visible
 * que le backend refuserait ensuite.
 */
const IncidentQueueView = () => {
  const [tab, setTab] = useState("a-traiter");
  const [page, setPage] = useState(1);
  const [showManualForm, setShowManualForm] = useState(false);
  const [openNode, setOpenNode] = useState(null);

  const activeTab = TABS.find((t) => t.key === tab);
  const { data: incidentsPage, isLoading } = useIncidentsList({
    status: activeTab.statusFilter, page, pageSize: 15,
  });
  const { data: openAlerts = [] } = useOpenAlerts(50);

  const acknowledge = useAcknowledgeIncident();
  const resolve = useResolveIncident();
  const canAck = useHasPermission(PERMISSIONS.ACKNOWLEDGE_INCIDENT);
  const canResolve = useHasPermission(PERMISSIONS.RESOLVE_INCIDENT);
  const canCreateManual = useHasPermission(PERMISSIONS.CREATE_MANUAL_INCIDENT);

  const sitesAffectes = useMemo(() => {
    const byLocality = new Map();
    for (const a of openAlerts) {
      const key = a.locality ?? "Localité inconnue";
      byLocality.set(key, (byLocality.get(key) ?? 0) + 1);
    }
    return [...byLocality.entries()].sort((a, b) => b[1] - a[1]);
  }, [openAlerts]);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold">File d'incidents — Agent NOC</h1>
          <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
            Traitement en direct des alertes de supervision
          </p>
        </div>
        {canCreateManual && (
          <button
            onClick={() => setShowManualForm(true)}
            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-white"
            style={{ background: "var(--color-accent)" }}
          >
            <PlusCircle className="h-3.5 w-3.5" /> Signaler un incident
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KPICard title="Alertes ouvertes" value={openAlerts.length} icon={AlertCircle} accent={STATUS.critical}
          sentiment={openAlerts.length > 0 ? "bad" : "good"} />
        <KPICard title="Sites affectés" value={sitesAffectes.length} icon={MapPin} accent={STATUS.warning} />
        <KPICard title="Critiques ouvertes" value={openAlerts.filter((a) => a.severity === "critical").length} icon={AlertCircle} accent={STATUS.critical} />
        <KPICard title="Hautes ouvertes" value={openAlerts.filter((a) => a.severity === "high").length} icon={AlertCircle} accent={STATUS.serious} />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        {/* Alertes temps réel */}
        <div style={{ height: 380 }} className="xl:col-span-2">
          <AlertFeed />
        </div>

        {/* Sites affectés */}
        <Card icon={MapPin} title="Sites affectés" subtitle="Regroupement des alertes ouvertes par localité" bodyClassName="p-0" className="flex h-[380px] flex-col">
          <ul className="min-h-0 flex-1 divide-y overflow-y-auto" style={{ borderColor: "var(--color-border)" }}>
            {sitesAffectes.map(([locality, count]) => (
              <li key={locality} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className="truncate" title={locality}>{locality}</span>
                <span className="font-mono text-xs font-semibold" style={{ color: STATUS.critical }}>{count}</span>
              </li>
            ))}
            {sitesAffectes.length === 0 && (
              <li className="px-3 py-6 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>Aucun site affecté actuellement.</li>
            )}
          </ul>
        </Card>
      </div>

      {/* Incidents à traiter / Actions en cours / Historique */}
      <Card
        icon={ListChecks}
        title="Incidents"
        action={
          <div className="flex gap-1 text-xs">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => { setTab(t.key); setPage(1); }}
                className="rounded-md px-2.5 py-1 font-medium"
                style={{
                  background: tab === t.key ? "var(--color-accent-soft)" : "transparent",
                  color: tab === t.key ? "var(--color-accent)" : "var(--color-text-secondary)",
                }}
              >
                {t.label}
              </button>
            ))}
          </div>
        }
        bodyClassName="p-0"
      >
        <IncidentQueueTable
          incidents={incidentsPage?.items ?? []}
          total={incidentsPage?.total}
          page={page}
          pageSize={15}
          onPageChange={setPage}
          loading={isLoading}
          canAcknowledge={canAck && tab !== "historique"}
          canResolve={canResolve}
          onAcknowledge={(id) => acknowledge.mutate(id)}
          onResolve={(id, notes) => resolve.mutate({ id, notes })}
          acknowledgingId={acknowledge.isPending ? acknowledge.variables : null}
          resolvingId={resolve.isPending ? resolve.variables?.id : null}
          onOpenNode={setOpenNode}
          emptyLabel={tab === "a-traiter" ? "Aucun incident à traiter — file vide." : "Aucun incident."}
        />
      </Card>

      <p className="flex items-center gap-1.5 text-xs" style={{ color: "var(--color-text-muted)" }}>
        <History className="h-3.5 w-3.5" /> L'onglet Historique couvre toute la période ; les autres se limitent à l'état courant.
      </p>

      {showManualForm && <ManualIncidentForm onClose={() => setShowManualForm(false)} />}
      {openNode && <NodeDetailDrawer nodeCode={openNode} onClose={() => setOpenNode(null)} />}
    </div>
  );
};

export default IncidentQueueView;

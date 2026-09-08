import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PlusCircle } from "lucide-react";

import IncidentDrawer from "../components/domain/IncidentDrawer";
import IncidentTable from "../components/domain/IncidentTable";
import ManualIncidentModal from "../components/domain/ManualIncidentModal";
import NetworkVitals from "../components/domain/NetworkVitals";
import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { PageHeader } from "../components/layout/TopBar";
import { Segmented } from "../components/ui/Controls";
import { StateDot } from "../components/ui/Badge";
import { ageFrom, num } from "../lib/format";
import { PERMISSIONS } from "../lib/permissions";
import { severityMeta } from "../lib/vocabulary";
import {
  useAlertSummary,
  useNetworkKpi,
  useNodeStates,
  useNodesDown,
  useOpenAlerts,
} from "../hooks/queries";
import { useCurrentUser, usePermission } from "../hooks/useSession";

/**
 * Console d'exploitation — NIVEAU 3 du document métier
 * (« Alertes temps réel | Incidents à traiter | Sites affectés |
 *   Historique | Actions en cours »).
 *
 * C'est l'écran du technicien NOC, celui qui reste ouvert huit heures.
 * Il est organisé autour d'UNE question : « qu'est-ce que je traite
 * maintenant ». D'où la file d'attente en pleine largeur à gauche et le
 * contexte réduit à droite — l'inverse (des vignettes partout et la file
 * reléguée en bas) est le défaut principal de l'ancienne interface.
 *
 * La file vient de /api/alerts/open et non de /api/incidents : cette
 * route renvoie déjà les incidents ouverts ET acquittés, hors fenêtres
 * de maintenance, triés par gravité puis par ancienneté — c'est-à-dire
 * exactement l'ordre de traitement, calculé par PostgreSQL.
 */
export default function ConsoleView() {
  const user = useCurrentUser();
  const canCreateManual = usePermission(PERMISSIONS.CREATE_MANUAL_INCIDENT);

  const [queue, setQueue] = useState("todo");
  const [selectedId, setSelectedId] = useState(null);
  const [manualOpen, setManualOpen] = useState(false);

  const alertsQuery = useOpenAlerts({ limit: 150 });
  const summary = useAlertSummary();
  const nodeStates = useNodeStates();
  const nodesDown = useNodesDown();
  const network = useNetworkKpi({ hours: 24 });

  // On mémoïse à partir de `alertsQuery.data` et non d'un `?? []`
  // intermédiaire : ce dernier crée un nouveau tableau à chaque rendu,
  // ce qui invalide le useMemo en permanence et refiltre 150 lignes à
  // chaque battement d'horloge.
  const alerts = alertsQuery.data;

  const buckets = useMemo(() => {
    const list = alerts ?? [];
    return {
      // « À traiter » = non acquitté OU non affecté. Un incident acquitté
      // mais laissé sans titulaire reste du travail en attente : le
      // masquer parce que quelqu'un a cliqué « acquitter » est la façon
      // la plus simple de perdre un ticket.
      todo: list.filter((a) => a.status === "open" || !a.assigned_to_user_id),
      mine: list.filter((a) => a.assigned_to_user_id === user?.id),
      all: list,
    };
  }, [alerts, user?.id]);

  const rows = buckets[queue] ?? [];

  const bySeverity = useMemo(() => {
    const counts = { critical: 0, high: 0, medium: 0, low: 0 };
    for (const alert of alerts ?? []) {
      if (counts[alert.severity] !== undefined) counts[alert.severity] += 1;
    }
    return counts;
  }, [alerts]);

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Console d'exploitation"
        subtitle="Alertes en cours, file de traitement et état du réseau en direct"
        actions={
          canCreateManual && (
            <button type="button" className="btn btn-sm" onClick={() => setManualOpen(true)}>
              <PlusCircle size={13} /> Signaler une panne
            </button>
          )
        }
      />

      {/* --- Compteurs de tension --- */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          label="À traiter"
          value={num(buckets.todo.length, "0")}
          color={buckets.todo.length ? "var(--sev-high)" : "var(--state-up)"}
          hint="non acquittés ou non affectés"
        />
        <Stat
          label="Mes incidents"
          value={num(buckets.mine.length, "0")}
          color={buckets.mine.length ? "var(--ink)" : "var(--ink-3)"}
          hint="qui me sont affectés"
        />
        <Stat
          label="Critiques"
          value={num(bySeverity.critical, "0")}
          color={bySeverity.critical ? "var(--sev-critical)" : "var(--state-up)"}
          status={bySeverity.critical ? "var(--sev-critical)" : undefined}
        />
        <Stat
          label="Majeurs"
          value={num(bySeverity.high, "0")}
          color={bySeverity.high ? "var(--sev-high)" : "var(--ink-2)"}
        />
        <Stat
          label="Plus ancien non acq."
          value={
            summary.data?.oldest_unacknowledged_at
              ? ageFrom(summary.data.oldest_unacknowledged_at)
              : "—"
          }
          color={summary.data?.oldest_unacknowledged_at ? "var(--sev-medium)" : "var(--state-up)"}
          hint="tension réelle de la salle"
        />
        <Stat
          label="Équipements HS"
          value={num(nodeStates.data?.down, "0")}
          color={nodeStates.data?.down ? "var(--state-down)" : "var(--state-up)"}
          to="/equipements?state=down"
          hint={`${num(nodeStates.data?.degraded, "0")} dégradés`}
        />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-4 gap-2.5">
        {/* --- File de traitement --- */}
        <div className="xl:col-span-3 min-w-0">
          <Panel
            title="File de traitement"
            accent="var(--sev-critical)"
            flush
            actions={
              <Segmented
                ariaLabel="Filtre de file"
                value={queue}
                onChange={setQueue}
                options={[
                  { value: "todo", label: `À traiter (${buckets.todo.length})` },
                  { value: "mine", label: `À moi (${buckets.mine.length})` },
                  { value: "all", label: `Tout (${buckets.all.length})` },
                ]}
              />
            }
          >
            <div style={{ maxHeight: "calc(100vh - 340px)", overflow: "auto" }}>
              <QueryBoundary
                query={alertsQuery}
                skeleton={<SkeletonRows rows={8} columns={6} />}
                empty={() => rows.length === 0}
                emptyMessage={
                  queue === "mine"
                    ? "Aucun incident ne vous est affecté."
                    : queue === "todo"
                      ? "File vide — tout est acquitté et affecté."
                      : "Aucune alerte ouverte."
                }
                emptyHint={
                  queue === "all"
                    ? "Le réseau est nominal, ou la collecte ETL ne remonte plus rien : vérifiez l'écran Collecte ETL."
                    : undefined
                }
              >
                <IncidentTable
                  incidents={rows}
                  selectedId={selectedId}
                  onSelect={(row) => setSelectedId(row.id)}
                />
              </QueryBoundary>
            </div>
          </Panel>
        </div>

        {/* --- Contexte --- */}
        <div className="space-y-2.5 min-w-0">
          <Panel
            title="Équipements hors service"
            accent="var(--state-down)"
            to="/equipements?state=down"
            flush
          >
            <QueryBoundary
              query={nodesDown}
              compact
              emptyMessage="Aucun équipement injoignable"
              emptyHint="Un équipement est déclaré hors service sur incident bloquant ouvert ou disponibilité nulle."
            >
              {(items) => (
                <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                  {items.slice(0, 10).map((node) => (
                    <li key={node.node_id}>
                      <Link
                        to={`/equipements/${node.node_id}`}
                        className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-2)]"
                        style={{ textDecoration: "none", color: "inherit" }}
                      >
                        <StateDot state="down" />
                        <span className="min-w-0 flex-1">
                          <span className="block text-[12px] font-medium truncate">
                            {node.node_name}
                          </span>
                          <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                            {node.locality}
                          </span>
                        </span>
                        <span className="num text-[11px]" style={{ color: "var(--sev-critical)" }}>
                          {node.since ? ageFrom(node.since) : "—"}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </QueryBoundary>
          </Panel>

          <Panel title="Réseau — 24 h" to="/performance" toLabel="Analyser">
            <div className="grid grid-cols-2 gap-2">
              <NetworkVitals
                data={network.data}
                expectedNodes={nodeStates.data?.total}
                compact
              />
            </div>
          </Panel>

          <Panel title="Répartition des alertes" flush>
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {["critical", "high", "medium", "low"].map((severity) => {
                const meta = severityMeta(severity);
                const count = bySeverity[severity];
                // `buckets.all` et non `alerts` : ce dernier vaut
                // `undefined` tant que la requête n'a pas répondu, et un
                // `.length` dessus fait planter tout l'écran au premier
                // rendu. `buckets` est memoïsé et toujours un tableau.
                const total = buckets.all.length;
                const share = total ? (count / total) * 100 : 0;
                return (
                  <li key={severity} className="flex items-center gap-2 px-2.5 py-1.5">
                    <span className="dot" style={{ background: meta.color }} />
                    <span className="text-[12px] flex-1">{meta.label}</span>
                    <div style={{ width: 60 }}>
                      <div
                        className="rounded-full overflow-hidden"
                        style={{ height: 4, background: "var(--surface-3)" }}
                      >
                        <div
                          style={{ width: `${share}%`, height: "100%", background: meta.color }}
                        />
                      </div>
                    </div>
                    <span className="num text-[12px]" style={{ width: 26, textAlign: "right" }}>
                      {count}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>
      </div>

      <IncidentDrawer
        incidentId={selectedId}
        open={Boolean(selectedId)}
        onClose={() => setSelectedId(null)}
      />
      <ManualIncidentModal open={manualOpen} onClose={() => setManualOpen(false)} />
    </div>
  );
}

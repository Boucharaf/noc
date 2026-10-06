import { useState } from "react";
import { CalendarPlus, Trash2 } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog, Modal } from "../components/ui/Overlay";
import { Field, Notice, Segmented } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { dateTime, duration, num } from "../lib/format";
import { errorMessage } from "../api/client";
import { toolLabel } from "../lib/vocabulary";
import { PERMISSIONS } from "../lib/permissions";
import { useMaintenanceActions, useMaintenanceWindows, useNodes, useReference } from "../hooks/queries";
import { usePermission } from "../hooks/useSession";

/**
 * Fenêtres de maintenance planifiée.
 *
 * Ce n'est pas un agenda : c'est un mécanisme de NEUTRALISATION. Une
 * fenêtre active exclut les incidents qu'elle couvre de tous les KPI et
 * du calcul de SLA (`v_incident.is_maintenance`). Une coupure voulue
 * comptée comme une panne fausse à la fois le volume d'incidents et la
 * conformité contractuelle — et c'est le reproche classique fait à un
 * NOC en comité de pilotage.
 *
 * Conséquence, rappelée dans l'interface : créer une fenêtre trop large
 * masque de vraies pannes. La portée (équipement OU site) est donc
 * obligatoire, jamais « tout le réseau ».
 */
export default function MaintenancePage() {
  const [filter, setFilter] = useState("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [toDelete, setToDelete] = useState(null);

  const canManage = usePermission(PERMISSIONS.MANAGE_MAINTENANCE);
  const windows = useMaintenanceWindows({ onlyActive: filter === "active", limit: 200 });
  const actions = useMaintenanceActions();

  const items = windows.data ?? [];
  const now = Date.now();
  const active = items.filter(
    (w) => new Date(w.starts_at).getTime() <= now && new Date(w.ends_at).getTime() >= now,
  );
  const upcoming = items.filter((w) => new Date(w.starts_at).getTime() > now);

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Maintenances planifiées"
        subtitle="Fenêtres pendant lesquelles les alertes ne comptent ni dans les KPI ni dans le SLA"
        actions={
          canManage && (
            <button type="button" className="btn btn-sm btn-primary" onClick={() => setCreateOpen(true)}>
              <CalendarPlus size={13} /> Planifier
            </button>
          )
        }
      />

      <div className="grid grid-cols-3 gap-2">
        <Stat
          label="En cours"
          value={num(active.length, "0")}
          color={active.length ? "var(--state-maintenance)" : "var(--ink-2)"}
          hint="alertes neutralisées"
        />
        <Stat label="À venir" value={num(upcoming.length, "0")} />
        <Stat label="Enregistrées" value={num(items.length, "0")} />
      </div>

      <Panel
        title="Fenêtres"
        flush
        actions={
          <Segmented
            ariaLabel="Filtre"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "all", label: "Toutes" },
              { value: "active", label: "En cours" },
            ]}
          />
        }
      >
        <QueryBoundary
          query={windows}
          emptyMessage="Aucune fenêtre de maintenance"
          emptyHint="Les fenêtres peuvent aussi être importées depuis les outils (mode maintenance Zabbix, downtime Centreon) via l'API interne de l'ETL."
        >
          {(rows) => (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 96 }}>État</th>
                  <th style={{ width: 200 }}>Portée</th>
                  <th>Motif</th>
                  <th style={{ width: 140 }}>Début</th>
                  <th style={{ width: 140 }}>Fin</th>
                  <th style={{ width: 80, textAlign: "right" }}>Durée</th>
                  <th style={{ width: 130 }}>Créée par</th>
                  {canManage && <th style={{ width: 40 }} />}
                </tr>
              </thead>
              <tbody>
                {rows.map((window) => {
                  const start = new Date(window.starts_at).getTime();
                  const end = new Date(window.ends_at).getTime();
                  const isActive = start <= now && end >= now;
                  const isPast = end < now;
                  return (
                    <tr key={window.id}>
                      <td>
                        <Badge
                          color={
                            isActive
                              ? "var(--state-maintenance)"
                              : isPast
                                ? "var(--ink-3)"
                                : "var(--sev-info)"
                          }
                        >
                          {isActive ? "En cours" : isPast ? "Terminée" : "À venir"}
                        </Badge>
                      </td>
                      <td>
                        {window.node_name ? (
                          <span>
                            {window.node_name}
                            <span className="text-[10.5px] ml-1" style={{ color: "var(--ink-3)" }}>
                              équipement
                            </span>
                          </span>
                        ) : window.locality_name ? (
                          <span>
                            {window.locality_name}
                            <span className="text-[10.5px] ml-1" style={{ color: "var(--ink-3)" }}>
                              site entier
                            </span>
                          </span>
                        ) : (
                          <span style={{ color: "var(--ink-3)" }}>—</span>
                        )}
                      </td>
                      <td className="truncate-cell" title={window.reason}>
                        {window.reason}
                        {!window.suppress_alerts && (
                          <span className="text-[10.5px] ml-1.5" style={{ color: "var(--sev-medium)" }}>
                            (alertes conservées)
                          </span>
                        )}
                      </td>
                      <td className="num" style={{ color: "var(--ink-2)" }}>
                        {dateTime(window.starts_at)}
                      </td>
                      <td className="num" style={{ color: "var(--ink-2)" }}>
                        {dateTime(window.ends_at)}
                      </td>
                      <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                        {duration((end - start) / 60000)}
                      </td>
                      <td style={{ color: "var(--ink-3)" }}>
                        {window.created_by_full_name ||
                          (window.source_tool ? toolLabel(window.source_tool) : "—")}
                      </td>
                      {canManage && (
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            onClick={() => setToDelete(window)}
                            title="Supprimer cette fenêtre"
                          >
                            <Trash2 size={12} />
                          </button>
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Panel>

      {createOpen && (
        <CreateWindowModal onClose={() => setCreateOpen(false)} create={actions.create} />
      )}

      <ConfirmDialog
        open={Boolean(toDelete)}
        onClose={() => setToDelete(null)}
        pending={actions.remove.isPending}
        title="Supprimer la fenêtre"
        message={
          toDelete
            ? `« ${toDelete.reason} » sera supprimée. Les incidents survenus pendant cette fenêtre redeviendront comptabilisés dans les KPI et le SLA.`
            : ""
        }
        confirmLabel="Supprimer"
        onConfirm={async () => {
          await actions.remove.mutateAsync(toDelete.id);
          setToDelete(null);
        }}
      />
    </div>
  );
}

function CreateWindowModal({ onClose, create }) {
  const { data: reference } = useReference();
  const [scope, setScope] = useState("node");
  const [search, setSearch] = useState("");
  const [nodeId, setNodeId] = useState(null);
  const [localityId, setLocalityId] = useState("");
  const [reason, setReason] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [suppress, setSuppress] = useState(true);
  const [error, setError] = useState(null);

  const nodes = useNodes({ q: search || undefined, page_size: 15, sort: "name" });

  const valid =
    reason.trim() &&
    startsAt &&
    endsAt &&
    new Date(endsAt) > new Date(startsAt) &&
    (scope === "node" ? nodeId : localityId);

  const submit = async () => {
    setError(null);
    try {
      await create.mutateAsync({
        node_id: scope === "node" ? Number(nodeId) : null,
        locality_id: scope === "locality" ? Number(localityId) : null,
        reason: reason.trim(),
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
        suppress_alerts: suppress,
      });
      onClose();
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Planifier une maintenance"
      subtitle="Les incidents survenus dans cette fenêtre seront exclus des KPI et du SLA."
      width={480}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!valid || create.isPending}
            onClick={submit}
          >
            {create.isPending ? "…" : "Planifier"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}

        <Field label="Portée" required>
          <Segmented
            ariaLabel="Portée"
            value={scope}
            onChange={setScope}
            options={[
              { value: "node", label: "Un équipement" },
              { value: "locality", label: "Un site entier" },
            ]}
          />
        </Field>

        {scope === "node" ? (
          <>
            <Field label="Équipement" required>
              <input
                className="input"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setNodeId(null);
                }}
                placeholder="Rechercher par nom ou IP…"
              />
            </Field>
            <div
              className="panel"
              style={{ maxHeight: 150, overflow: "auto", background: "var(--surface-2)" }}
            >
              <QueryBoundary query={nodes} compact empty={(d) => !d?.items?.length}>
                {(data) => (
                  <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                    {data.items.map((node) => (
                      <li key={node.node_id}>
                        <button
                          type="button"
                          className="w-full text-left px-2.5 py-1.5"
                          style={{
                            background:
                              Number(nodeId) === node.node_id ? "var(--accent-soft)" : undefined,
                          }}
                          onClick={() => setNodeId(node.node_id)}
                        >
                          <span className="text-[12px]">{node.name}</span>
                          <span className="text-[10.5px] ml-2" style={{ color: "var(--ink-3)" }}>
                            {node.locality}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </QueryBoundary>
            </div>
          </>
        ) : (
          <Field
            label="Site"
            required
            hint="Tous les équipements du site verront leurs alertes neutralisées."
          >
            <select
              className="select"
              value={localityId}
              onChange={(event) => setLocalityId(event.target.value)}
            >
              <option value="">Choisir un site…</option>
              {(reference?.localities ?? []).map((locality) => (
                <option key={locality.id} value={locality.id}>
                  {locality.name} ({locality.nb_nodes} équip.)
                </option>
              ))}
            </select>
          </Field>
        )}

        <Field label="Motif" required>
          <input
            className="input"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Mise à jour firmware, bascule électrique…"
          />
        </Field>

        <div className="grid grid-cols-2 gap-2">
          <Field label="Début" required>
            <input
              className="input"
              type="datetime-local"
              value={startsAt}
              onChange={(event) => setStartsAt(event.target.value)}
            />
          </Field>
          <Field
            label="Fin"
            required
            error={
              startsAt && endsAt && new Date(endsAt) <= new Date(startsAt)
                ? "La fin doit être postérieure au début."
                : null
            }
          >
            <input
              className="input"
              type="datetime-local"
              value={endsAt}
              onChange={(event) => setEndsAt(event.target.value)}
            />
          </Field>
        </div>

        <label className="flex items-center gap-2 text-[12px]">
          <input
            type="checkbox"
            checked={suppress}
            onChange={(event) => setSuppress(event.target.checked)}
          />
          Neutraliser les alertes (exclusion des KPI et du SLA)
        </label>
        <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          Décochez pour enregistrer une intervention à titre documentaire, sans modifier
          les indicateurs.
        </p>
      </div>
    </Modal>
  );
}

import { useState } from "react";
import { Link } from "react-router-dom";
import { Camera, MapPin, Navigation, PlusCircle } from "lucide-react";

import IncidentDrawer from "../components/domain/IncidentDrawer";
import ManualIncidentModal from "../components/domain/ManualIncidentModal";
import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { Field, Notice, Segmented } from "../components/ui/Controls";
import { FieldStatusBadge, SeverityBadge } from "../components/ui/Badge";
import { Modal } from "../components/ui/Overlay";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { ageFrom, dateTime, ellipsis, num, smartTime } from "../lib/format";
import { errorMessage } from "../api/client";
import {
  useFieldActions,
  useFieldInterventions,
  useNodes,
  useOpenAlerts,
} from "../hooks/queries";

/**
 * Vue terrain — l'agent en déplacement.
 *
 * Conçue pour un téléphone tenu d'une main devant une baie : cibles
 * tactiles hautes (36 px), une action principale par carte, aucun
 * tableau à défilement horizontal.
 *
 * Contrainte d'API à connaître : le rôle `agent_terrain` n'a PAS accès à
 * `GET /api/incidents` (403 — voir routes/incidents.py::_VIEW_HISTORY).
 * Cet écran lit donc les alertes via `/api/alerts/open`, qui est ouverte
 * à tous les comptes connectés. Le détail d'un incident précis
 * (`/api/incidents/{id}`) reste accessible, d'où le tiroir de détail.
 *
 * Le relevé GPS au moment du compte rendu n'est pas un gadget : il
 * atteste du passage sur site, ce que le rapport mensuel exploite.
 */

const STATUS_FLOW = {
  scheduled: { next: "en_route", label: "Je pars" },
  en_route: { next: "on_site", label: "Je suis sur site" },
  on_site: { next: null, label: "Rédiger le compte rendu" },
};

export default function TerrainView() {
  const [filter, setFilter] = useState("active");
  const [reportFor, setReportFor] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [manualOpen, setManualOpen] = useState(false);
  const [selectedIncident, setSelectedIncident] = useState(null);

  const interventions = useFieldInterventions();
  const alerts = useOpenAlerts({ limit: 30 });
  const actions = useFieldActions();

  const all = interventions.data ?? [];
  const active = all.filter((item) => ["scheduled", "en_route", "on_site"].includes(item.status));
  const done = all.filter((item) => ["done", "cancelled"].includes(item.status));
  const rows = filter === "active" ? active : filter === "done" ? done : all;

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Tournée"
        subtitle="Interventions planifiées, comptes rendus et alertes en cours"
        actions={
          <>
            <button type="button" className="btn btn-sm" onClick={() => setCreateOpen(true)}>
              <PlusCircle size={13} /> Programmer
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setManualOpen(true)}>
              Signaler une panne
            </button>
          </>
        }
      />

      <div className="grid grid-cols-3 gap-2">
        <Stat label="À faire" value={num(active.length, "0")} color={active.length ? "var(--sev-medium)" : "var(--state-up)"} />
        <Stat
          label="Sur site"
          value={num(all.filter((i) => i.status === "on_site").length, "0")}
          color="var(--accent-ink)"
        />
        <Stat label="Terminées" value={num(done.length, "0")} color="var(--state-up)" />
      </div>

      <Panel
        title="Mes interventions"
        actions={
          <Segmented
            ariaLabel="Filtre d'interventions"
            value={filter}
            onChange={setFilter}
            options={[
              { value: "active", label: `En cours (${active.length})` },
              { value: "done", label: `Terminées (${done.length})` },
              { value: "all", label: "Toutes" },
            ]}
          />
        }
      >
        <QueryBoundary
          query={interventions}
          empty={() => rows.length === 0}
          emptyMessage="Aucune intervention"
          emptyHint="Le Chef NOC en programme depuis la salle, ou vous pouvez en créer une avec « Programmer »."
        >
          <ul className="space-y-2">
            {rows.map((intervention) => {
              const flow = STATUS_FLOW[intervention.status];
              return (
                <li
                  key={intervention.id}
                  className="panel p-2.5"
                  style={{ background: "var(--surface-2)" }}
                >
                  <div className="flex items-start gap-2 flex-wrap">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Link
                          to={`/equipements/${encodeURIComponent(intervention.node_key ?? intervention.node_id)}`}
                          className="text-[13px] font-semibold"
                          style={{ color: "var(--ink)", textDecoration: "none" }}
                        >
                          {intervention.node_name}
                        </Link>
                        <FieldStatusBadge status={intervention.status} />
                      </div>
                      <div className="text-[11.5px] mt-0.5" style={{ color: "var(--ink-3)" }}>
                        <MapPin size={10} className="inline mr-1" />
                        {intervention.locality}
                        {intervention.scheduled_at && (
                          <> · prévue {smartTime(intervention.scheduled_at)}</>
                        )}
                        {intervention.incident_id && (
                          <>
                            {" · "}
                            <button
                              type="button"
                              className="underline"
                              style={{ color: "var(--accent-ink)" }}
                              onClick={() => setSelectedIncident(intervention.incident_id)}
                            >
                              incident #{intervention.incident_id}
                            </button>
                          </>
                        )}
                      </div>
                      {intervention.report_text && (
                        <p className="text-[12px] mt-1.5" style={{ color: "var(--ink-2)" }}>
                          {intervention.report_text}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5">
                      {flow?.next && (
                        <button
                          type="button"
                          className="btn btn-primary"
                          style={{ height: 34 }}
                          disabled={actions.updateStatus.isPending}
                          onClick={() =>
                            actions.updateStatus.mutate({
                              id: intervention.id,
                              status: flow.next,
                            })
                          }
                        >
                          <Navigation size={13} /> {flow.label}
                        </button>
                      )}
                      {intervention.status === "on_site" && (
                        <button
                          type="button"
                          className="btn btn-primary"
                          style={{ height: 34 }}
                          onClick={() => setReportFor(intervention)}
                        >
                          <Camera size={13} /> Compte rendu
                        </button>
                      )}
                      {intervention.status === "done" && intervention.completed_at && (
                        <span className="text-[11px] num" style={{ color: "var(--ink-3)" }}>
                          {dateTime(intervention.completed_at)}
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </QueryBoundary>
      </Panel>

      <Panel title="Alertes en cours sur le réseau" accent="var(--sev-high)" flush>
        <QueryBoundary query={alerts} compact emptyMessage="Aucune alerte ouverte">
          {(items) => (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {items.slice(0, 12).map((alert) => (
                <li key={alert.id}>
                  <button
                    type="button"
                    className="w-full text-left flex items-start gap-2 px-2.5 py-2 hover:bg-[var(--surface-2)]"
                    onClick={() => setSelectedIncident(alert.id)}
                  >
                    <SeverityBadge severity={alert.severity} short />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-medium">
                        {alert.node_name}
                        <span className="font-normal ml-1.5" style={{ color: "var(--ink-3)" }}>
                          {alert.locality}
                        </span>
                      </span>
                      <span className="block text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                        {ellipsis(alert.description, 80)}
                      </span>
                    </span>
                    <span className="num text-[11px] shrink-0" style={{ color: "var(--sev-medium)" }}>
                      {ageFrom(alert.detected_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </QueryBoundary>
      </Panel>

      <ReportModal
        intervention={reportFor}
        onClose={() => setReportFor(null)}
        onSubmit={actions.submitReport}
      />
      <CreateInterventionModal open={createOpen} onClose={() => setCreateOpen(false)} onSubmit={actions.create} />
      <ManualIncidentModal open={manualOpen} onClose={() => setManualOpen(false)} />
      <IncidentDrawer
        incidentId={selectedIncident}
        open={Boolean(selectedIncident)}
        onClose={() => setSelectedIncident(null)}
      />
    </div>
  );
}

/** Compte rendu d'intervention, avec relevé GPS facultatif. */
function ReportModal({ intervention, onClose, onSubmit }) {
  const [text, setText] = useState("");
  const [position, setPosition] = useState(null);
  const [geoError, setGeoError] = useState(null);
  const [error, setError] = useState(null);

  const capturePosition = () => {
    setGeoError(null);
    if (!navigator.geolocation) {
      setGeoError("Ce navigateur ne fournit pas de position.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (result) =>
        setPosition({
          latitude: result.coords.latitude,
          longitude: result.coords.longitude,
        }),
      // Message explicite : « échec » sans raison laisse l'agent
      // recommencer indéfiniment alors que le GPS est simplement refusé.
      (positionError) =>
        setGeoError(
          positionError.code === positionError.PERMISSION_DENIED
            ? "Localisation refusée. Le compte rendu reste valide sans position."
            : "Position indisponible (pas de signal GPS ?).",
        ),
      { enableHighAccuracy: true, timeout: 8000 },
    );
  };

  const submit = async () => {
    setError(null);
    try {
      await onSubmit.mutateAsync({
        id: intervention.id,
        payload: {
          report_text: text.trim(),
          checkin_latitude: position?.latitude ?? null,
          checkin_longitude: position?.longitude ?? null,
          photo_urls: [],
        },
      });
      setText("");
      setPosition(null);
      onClose();
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open={Boolean(intervention)}
      onClose={onClose}
      title="Compte rendu d'intervention"
      subtitle={intervention ? `${intervention.node_name} · ${intervention.locality}` : undefined}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!text.trim() || onSubmit.isPending}
            onClick={submit}
          >
            {onSubmit.isPending ? "Envoi…" : "Clôturer l'intervention"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
        <Field
          label="Ce qui a été fait"
          required
          hint="Constat, action réalisée, pièces remplacées, état à la sortie."
        >
          <textarea
            className="textarea"
            rows={5}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Onduleur redémarré, batterie 2 remplacée, liaison rétablie à 11h40."
          />
        </Field>

        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" className="btn btn-sm" onClick={capturePosition}>
            <MapPin size={13} /> Relever ma position
          </button>
          {position && (
            <span className="num text-[11px]" style={{ color: "var(--state-up)" }}>
              {position.latitude.toFixed(5)}, {position.longitude.toFixed(5)}
            </span>
          )}
          {geoError && (
            <span className="text-[11px]" style={{ color: "var(--sev-medium)" }}>
              {geoError}
            </span>
          )}
        </div>
        <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          La position atteste du passage sur site dans le rapport mensuel. Elle reste
          facultative.
        </p>
      </div>
    </Modal>
  );
}

/** Programmation d'une intervention sur un équipement. */
function CreateInterventionModal({ open, onClose, onSubmit }) {
  const [search, setSearch] = useState("");
  const [nodeId, setNodeId] = useState(null);
  const [scheduledAt, setScheduledAt] = useState("");
  const [error, setError] = useState(null);

  const nodes = useNodes({ q: search || undefined, page_size: 20, sort: "state" });

  const submit = async () => {
    setError(null);
    try {
      await onSubmit.mutateAsync({
        // Clé textuelle (`netxms:464322`) : la convertir en nombre donnait NaN.
        node_key: nodeId,
        incident_id: null,
        scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
      });
      setNodeId(null);
      setSearch("");
      setScheduledAt("");
      onClose();
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Programmer une intervention"
      width={440}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!nodeId || onSubmit.isPending}
            onClick={submit}
          >
            {onSubmit.isPending ? "…" : "Programmer"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Équipement" required hint="Tapez un nom ou une adresse IP.">
          <input
            className="input"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setNodeId(null);
            }}
            placeholder="RTR-OUA…"
          />
        </Field>

        <div
          className="panel"
          style={{ maxHeight: 190, overflow: "auto", background: "var(--surface-2)" }}
        >
          <QueryBoundary query={nodes} compact empty={(d) => !d?.items?.length}>
            {(data) => (
              <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
                {data.items.map((node) => (
                  <li key={node.node_id}>
                    <button
                      type="button"
                      className="w-full text-left px-2.5 py-1.5 hover:bg-[var(--surface-3)]"
                      style={{
                        background:
                          nodeId === node.node_id ? "var(--accent-soft)" : undefined,
                      }}
                      onClick={() => setNodeId(node.node_id)}
                    >
                      <span className="text-[12px] font-medium">{node.name}</span>
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

        <Field label="Date et heure prévues" hint="Facultatif — laissez vide pour « dès que possible ».">
          <input
            className="input"
            type="datetime-local"
            value={scheduledAt}
            onChange={(event) => setScheduledAt(event.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}

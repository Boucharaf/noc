import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpCircle, Check, MessageSquare, UserPlus } from "lucide-react";

import { Drawer } from "../ui/Overlay";
import { ErrorState, LoadingState } from "../ui/States";
import { Field, Notice } from "../ui/Controls";
import { SeverityBadge, StatusBadge, ToolTag } from "../ui/Badge";
import { DefRow } from "../ui/Stat";
import { PERMISSIONS, ROLE_LABEL } from "../../lib/permissions";
import { dateTime, duration, smartTime } from "../../lib/format";
import { errorMessage } from "../../api/client";
import { timelineActionLabel } from "../../lib/vocabulary";
import { useIncident, useIncidentActions, useUsers } from "../../hooks/queries";
import { usePermission } from "../../hooks/useSession";

/**
 * Fiche d'incident et gestes de traitement.
 *
 * Toute la boucle d'exploitation tient ici : acquitter, affecter,
 * escalader, commenter, résoudre — sans quitter la file d'attente
 * affichée derrière. C'est le principal reproche adressé à l'ancienne
 * interface : chaque action renvoyait vers un écran séparé, et
 * l'opérateur perdait son filtre et sa position de lecture à chaque
 * ticket traité.
 *
 * Les boutons sont MASQUÉS quand le rôle ne les autorise pas, plutôt que
 * désactivés : un bouton grisé invite à chercher pourquoi, alors que la
 * réponse (« ce n'est pas votre métier ») ne changera pas.
 */

const RESOLVE_MIN_LENGTH = 1;

export default function IncidentDrawer({ incidentId, open, onClose }) {
  const query = useIncident(open ? incidentId : null);
  const actions = useIncidentActions();
  const { data: users } = useUsers();

  const canAcknowledge = usePermission(PERMISSIONS.ACKNOWLEDGE_INCIDENT);
  const canResolve = usePermission(PERMISSIONS.RESOLVE_INCIDENT);
  const canAssign = usePermission(PERMISSIONS.ASSIGN_INCIDENT);
  const canEscalate = usePermission(PERMISSIONS.ESCALATE_INCIDENT);

  const [panel, setPanel] = useState(null); // resolve | assign | escalate | comment
  const [text, setText] = useState("");
  const [targetUserId, setTargetUserId] = useState("");
  const [feedback, setFeedback] = useState(null);

  const incident = query.data;

  // Candidats à l'affectation : uniquement les profils qui traitent
  // réellement des incidents. Proposer un directeur dans cette liste
  // n'aurait aucun sens opérationnel.
  const assignable = useMemo(
    () => (users ?? []).filter((u) => u.is_active && ["technicien", "chef_noc", "agent_terrain"].includes(u.role)),
    [users],
  );
  const escalationTargets = useMemo(
    () => (users ?? []).filter((u) => u.is_active && ["chef_noc", "directeur"].includes(u.role)),
    [users],
  );

  const reset = () => {
    setPanel(null);
    setText("");
    setTargetUserId("");
  };

  const run = async (promise, successMessage) => {
    setFeedback(null);
    try {
      await promise;
      setFeedback({ tone: "success", message: successMessage });
      reset();
    } catch (error) {
      setFeedback({ tone: "error", message: errorMessage(error) });
    }
  };

  const busy =
    actions.acknowledge.isPending ||
    actions.resolve.isPending ||
    actions.assign.isPending ||
    actions.escalate.isPending ||
    actions.comment.isPending;

  const isClosed = incident?.status === "resolved" || incident?.status === "closed";

  return (
    <Drawer
      open={open}
      onClose={() => {
        reset();
        setFeedback(null);
        onClose();
      }}
      title={incident ? `Incident #${incident.id}` : "Incident"}
      badge={incident && <SeverityBadge severity={incident.severity} />}
      subtitle={
        incident
          ? `${incident.node_name} · ${incident.locality}${
              incident.region ? ` · ${incident.region}` : ""
            }`
          : undefined
      }
      width={620}
      footer={
        incident && (
          <>
            {canAcknowledge && incident.status === "open" && (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                disabled={busy}
                onClick={() =>
                  run(actions.acknowledge.mutateAsync(incident.id), "Incident acquitté.")
                }
              >
                <Check size={13} /> Acquitter
              </button>
            )}
            {canResolve && !isClosed && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy}
                onClick={() => setPanel(panel === "resolve" ? null : "resolve")}
              >
                <Check size={13} /> Résoudre
              </button>
            )}
            {canAssign && !isClosed && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy}
                onClick={() => setPanel(panel === "assign" ? null : "assign")}
              >
                <UserPlus size={13} /> Affecter
              </button>
            )}
            {canEscalate && !isClosed && (
              <button
                type="button"
                className="btn btn-sm"
                disabled={busy}
                onClick={() => setPanel(panel === "escalate" ? null : "escalate")}
              >
                <ArrowUpCircle size={13} /> Escalader
              </button>
            )}
            <button
              type="button"
              className="btn btn-sm ml-auto"
              disabled={busy}
              onClick={() => setPanel(panel === "comment" ? null : "comment")}
            >
              <MessageSquare size={13} /> Commenter
            </button>
          </>
        )
      }
    >
      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={query.refetch} />}

      {incident && (
        <div className="space-y-3">
          {feedback && (
            <Notice tone={feedback.tone} onClose={() => setFeedback(null)}>
              {feedback.message}
            </Notice>
          )}

          {incident.is_maintenance && (
            <Notice tone="info">
              Cet incident est tombé pendant une fenêtre de maintenance planifiée. Il est
              exclu des KPI et du calcul de SLA.
            </Notice>
          )}

          {/* --- Formulaire d'action contextuel --- */}
          {panel && (
            <div
              className="panel p-2.5 space-y-2"
              style={{ borderColor: "var(--border-strong)", background: "var(--surface-2)" }}
            >
              {panel === "resolve" && (
                <>
                  <Field
                    label="Compte rendu de résolution"
                    required
                    hint="Ce texte est archivé dans la chronologie et repris dans le rapport mensuel."
                  >
                    <textarea
                      className="textarea"
                      rows={3}
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="Action réalisée, cause confirmée, remise en service…"
                    />
                  </Field>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || text.trim().length < RESOLVE_MIN_LENGTH}
                    onClick={() =>
                      run(
                        actions.resolve.mutateAsync({ id: incident.id, notes: text.trim() }),
                        "Incident résolu.",
                      )
                    }
                  >
                    Confirmer la résolution
                  </button>
                </>
              )}

              {panel === "assign" && (
                <>
                  <Field label="Affecter à" required>
                    <select
                      className="select"
                      value={targetUserId}
                      onChange={(event) => setTargetUserId(event.target.value)}
                    >
                      <option value="">Choisir un intervenant…</option>
                      {assignable.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.full_name || user.username} — {ROLE_LABEL[user.role] ?? user.role}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Consigne (facultatif)">
                    <input
                      className="input"
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="Contexte, priorité, contact sur site…"
                    />
                  </Field>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || !targetUserId}
                    onClick={() =>
                      run(
                        actions.assign.mutateAsync({
                          id: incident.id,
                          userId: Number(targetUserId),
                          note: text.trim() || null,
                        }),
                        "Incident affecté.",
                      )
                    }
                  >
                    Affecter
                  </button>
                </>
              )}

              {panel === "escalate" && (
                <>
                  <Field label="Escalader vers" required>
                    <select
                      className="select"
                      value={targetUserId}
                      onChange={(event) => setTargetUserId(event.target.value)}
                    >
                      <option value="">Choisir un destinataire…</option>
                      {escalationTargets.map((user) => (
                        <option key={user.id} value={user.id}>
                          {user.full_name || user.username} — {ROLE_LABEL[user.role] ?? user.role}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Motif de l'escalade" required>
                    <textarea
                      className="textarea"
                      rows={2}
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="Pourquoi le niveau courant ne peut pas traiter…"
                    />
                  </Field>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || !targetUserId || !text.trim()}
                    onClick={() =>
                      run(
                        actions.escalate.mutateAsync({
                          id: incident.id,
                          userId: Number(targetUserId),
                          reason: text.trim(),
                        }),
                        "Incident escaladé.",
                      )
                    }
                  >
                    Escalader
                  </button>
                </>
              )}

              {panel === "comment" && (
                <>
                  <Field label="Commentaire">
                    <textarea
                      className="textarea"
                      rows={2}
                      value={text}
                      onChange={(event) => setText(event.target.value)}
                      placeholder="Observation, diagnostic intermédiaire, relance…"
                    />
                  </Field>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={busy || !text.trim()}
                    onClick={() =>
                      run(
                        actions.comment.mutateAsync({ id: incident.id, note: text.trim() }),
                        "Commentaire ajouté.",
                      )
                    }
                  >
                    Ajouter
                  </button>
                </>
              )}
            </div>
          )}

          {/* --- Description --- */}
          <div className="panel p-2.5" style={{ background: "var(--surface-2)" }}>
            <p className="text-[12.5px] leading-relaxed">
              {incident.description || "Aucune description fournie par l'outil source."}
            </p>
          </div>

          {/* --- Caractéristiques --- */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
            <div>
              <DefRow label="Statut">
                <StatusBadge status={incident.status} />
              </DefRow>
              <DefRow label="Détecté" mono>
                {dateTime(incident.detected_at)}
              </DefRow>
              <DefRow label="Acquitté" mono>
                {incident.acknowledged_at ? dateTime(incident.acknowledged_at) : "—"}
              </DefRow>
              <DefRow label="Résolu" mono>
                {incident.resolved_at ? dateTime(incident.resolved_at) : "—"}
              </DefRow>
              <DefRow label="MTTA" mono>
                {duration(incident.mtta_minutes)}
              </DefRow>
              <DefRow label="MTTR" mono>
                {duration(incident.mttr_minutes)}
              </DefRow>
            </div>
            <div>
              <DefRow label="Équipement">
                {incident.node_id ? (
                  <Link to={`/equipements/${incident.node_id}`} style={{ color: "var(--accent-ink)" }}>
                    {incident.node_name}
                  </Link>
                ) : (
                  incident.node_name
                )}
              </DefRow>
              <DefRow label="Site">{incident.locality}</DefRow>
              <DefRow label="Ministère">{incident.ministry || "—"}</DefRow>
              <DefRow label="Cause">
                {incident.cause_label || incident.cause_category || "Non identifiée"}
              </DefRow>
              <DefRow label="Source">
                <ToolTag tool={incident.source_tool} />
                {incident.external_id && (
                  <span className="mono-xs ml-1.5" style={{ color: "var(--ink-3)" }}>
                    {incident.external_id}
                  </span>
                )}
              </DefRow>
              <DefRow label="Affecté à">
                {incident.assigned_to_full_name || "Personne"}
              </DefRow>
              {incident.itop_ticket_ref && (
                <DefRow label="Ticket iTop" mono>
                  {incident.itop_ticket_ref}
                </DefRow>
              )}
              {incident.escalation_level > 0 && (
                <DefRow label="Escalade">
                  Niveau <span className="num">{incident.escalation_level}</span>
                </DefRow>
              )}
            </div>
          </div>

          {/* --- Chronologie --- */}
          <div>
            <h3 className="panel-title mb-1.5">Chronologie</h3>
            {incident.timeline?.length ? (
              <ol className="space-y-0">
                {incident.timeline.map((entry) => (
                  <li
                    key={entry.id}
                    className="flex gap-2 py-1.5 border-b last:border-0"
                    style={{ borderColor: "var(--border)" }}
                  >
                    <span
                      className="num text-[11px] shrink-0 pt-px"
                      style={{ color: "var(--ink-3)", width: 92 }}
                      title={dateTime(entry.created_at)}
                    >
                      {smartTime(entry.created_at)}
                    </span>
                    <div className="min-w-0">
                      <span className="text-[12px] font-medium">
                        {timelineActionLabel(entry.action)}
                      </span>
                      <span className="text-[11.5px] ml-1.5" style={{ color: "var(--ink-3)" }}>
                        {entry.user_full_name || "Système"}
                      </span>
                      {entry.note && (
                        <p className="text-[12px] mt-0.5" style={{ color: "var(--ink-2)" }}>
                          {entry.note}
                        </p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                Aucune action humaine enregistrée. L'incident vient de l'outil source et
                n'a pas encore été pris en charge.
              </p>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

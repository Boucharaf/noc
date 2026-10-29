import { Link } from "react-router-dom";

import LocationLink from "./LocationLink";
import { Drawer } from "../ui/Overlay";
import { Badge, NodeStateBadge, SeverityBadge, ToolTag } from "../ui/Badge";
import { DefRow } from "../ui/Stat";
import { EmptyState, ErrorState, LoadingState } from "../ui/States";
import { dateTime, duration, smartTime } from "../../lib/format";
import { itopStatusMeta, priorityLabel, slaStatusMeta } from "../../lib/itop";
import { toolLabel } from "../../lib/vocabulary";
import { useItopIncident } from "../../hooks/queries";
import { useScopeStore } from "../../store/scope";

/**
 * Fiche d'un incident iTop.
 *
 * Deux regards sur le même problème, côte à côte :
 *   1. ce qu'en dit iTop — le ticket, qui le traite, depuis quand, avec
 *      quel engagement de délai ;
 *   2. ce qu'en disent les OUTILS — l'état de l'équipement concerné chez
 *      Zabbix, Centreon, NetXMS, Nagios ou NSP, et les alertes techniques
 *      en cours qui expliquent l'incident.
 *
 * Aucune action de traitement ici : un incident se traite dans iTop, qui
 * reste la référence. Le NOC éclaire la décision, il ne double pas l'outil.
 */
function Section({ title, children, aside }) {
  return (
    <section className="mb-3">
      <div className="flex items-center gap-2 mb-1">
        <h3
          className="text-[10.5px] font-semibold uppercase tracking-[0.07em]"
          style={{ color: "var(--ink-3)" }}
        >
          {title}
        </h3>
        {aside && <span className="ml-auto">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function SlaLine({ label, value, target }) {
  if (value == null && target == null) return <DefRow label={label}>—</DefRow>;
  const over = value != null && target != null && value > target;
  return (
    <DefRow label={label}>
      <span style={{ color: over ? "var(--sev-critical)" : undefined }}>{duration(value)}</span>
      {target != null && (
        <span className="text-[11px] ml-1.5" style={{ color: "var(--ink-3)" }}>
          objectif {duration(target)}
        </span>
      )}
    </DefRow>
  );
}

export default function ItopIncidentDrawer({ incidentKey, open, onClose }) {
  const query = useItopIncident(open ? incidentKey : null);
  const setPath = useScopeStore((s) => s.setPath);
  const incident = query.data;
  const sla = incident?.sla ?? {};
  const slaMeta = slaStatusMeta(sla.ttr_status);
  const status = itopStatusMeta(incident?.status);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={620}
      title={incident ? `${incident.ref ?? incident.key} — ${incident.title}` : "Incident"}
      badge={incident && <SeverityBadge severity={incident.severity} />}
      subtitle={
        incident && (
          <span className="flex flex-wrap items-center gap-2">
            <Badge color={status.color}>{status.label}</Badge>
            <Badge color={slaMeta.color}>SLA : {slaMeta.label}</Badge>
            <span>ouvert {smartTime(incident.opened_at)}</span>
            {incident.agent ? <span>· {incident.agent}</span> : <span>· non affecté</span>}
          </span>
        )
      }
    >
      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={query.refetch} />}
      {incident && (
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Section title="Ticket iTop">
            <DefRow label="Référence" mono>{incident.ref}</DefRow>
            <DefRow label="Type">{incident.class === "UserRequest" ? "Demande" : "Incident"}</DefRow>
            <DefRow label="Priorité">{priorityLabel(incident.priority)}</DefRow>
            <DefRow label="Urgence / impact">
              {[incident.itop?.urgency, incident.itop?.impact].filter(Boolean).join(" / ") || "—"}
            </DefRow>
            <DefRow label="Organisation">{incident.organisation}</DefRow>
            <DefRow label="Demandeur">{incident.caller}</DefRow>
            <DefRow label="Équipe">{incident.team}</DefRow>
            <DefRow label="Agent">{incident.agent ?? "non affecté"}</DefRow>
            {incident.trigger && (
              <DefRow label="Événement Zabbix" mono>
                {incident.trigger.ref}
                <span className="ml-1.5 text-[11px]" style={{ color: "var(--ink-3)" }}>
                  {incident.trigger.active ? "problème en cours" : "problème clos dans Zabbix"}
                </span>
              </DefRow>
            )}
          </Section>

          <Section title="Délais et engagement">
            <DefRow label="Ouvert le">{dateTime(incident.opened_at)}</DefRow>
            <DefRow label="Pris en charge">{dateTime(incident.assigned_at)}</DefRow>
            <SlaLine
              label="Prise en charge"
              value={sla.tto_minutes}
              target={sla.tto_target_minutes}
            />
            <SlaLine
              label={sla.ttr_minutes != null ? "Résolution" : "Écoulé"}
              value={sla.ttr_minutes ?? sla.elapsed_minutes}
              target={sla.ttr_target_minutes}
            />
            {sla.ttr_remaining_minutes != null && (
              <DefRow label="Reste">{duration(sla.ttr_remaining_minutes)}</DefRow>
            )}
          </Section>

          <Section
            title="Localisation"
            aside={
              incident.site && (
                <Link
                  to="/territoire"
                  className="btn btn-ghost btn-sm"
                  onClick={() =>
                    setPath({
                      region: incident.region ?? null,
                      province: incident.province ?? null,
                      site: incident.site,
                    })
                  }
                >
                  Voir le site ›
                </Link>
              )
            }
          >
            <DefRow label="Lieu">
              <LocationLink
                site={incident.site}
                province={incident.province}
                region={incident.region}
                position={incident.position}
                name={incident.node_name}
              />
            </DefRow>
            <DefRow label={incident.cis?.some((ci) => ci.from_title) ? "Équipement" : "CI iTop"}>
              {incident.cis?.length
                ? incident.cis.map((ci) => ci.name).filter(Boolean).join(", ")
                : "aucun CI rattaché"}
              {incident.cis?.some((ci) => ci.from_title) && (
                <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                  cité dans le titre du ticket — aucun CI lié dans iTop
                </span>
              )}
            </DefRow>
          </Section>

          <Section
            title="Vue des outils"
            aside={
              incident.node && (
                <Link
                  to={`/equipements/${encodeURIComponent(incident.node.id)}`}
                  className="btn btn-ghost btn-sm"
                >
                  Fiche équipement ›
                </Link>
              )
            }
          >
            {!incident.tool_views?.length ? (
              <EmptyState
                compact
                message="Équipement non retrouvé dans la supervision"
                hint="Le CI iTop ne correspond à aucun équipement supervisé (nom ou référence)."
              />
            ) : (
              incident.tool_views.map((view) => (
                <div key={view.node_key} className="mb-1.5">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium truncate">{view.name}</span>
                    <NodeStateBadge state={view.state} />
                  </div>
                  <div className="flex flex-wrap gap-x-3 text-[11px]" style={{ color: "var(--ink-3)" }}>
                    {Object.entries(view.sources).map(([tool, ref]) => (
                      <span key={tool} title={`Référence ${toolLabel(tool)} : ${ref}`}>
                        {toolLabel(tool)}
                        {view.state_conflict?.[tool] ? ` : ${view.state_conflict[tool]}` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              ))
            )}
          </Section>

          <div className="sm:col-span-2">
            <Section
              title={`Alertes techniques liées (${incident.alerts?.length ?? 0})`}
            >
              {!incident.alerts?.length ? (
                <EmptyState
                  compact
                  message="Aucune alerte en cours sur cet équipement"
                  hint="Les outils de supervision ne signalent rien actuellement."
                />
              ) : (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th style={{ width: 92 }}>Gravité</th>
                      <th style={{ width: 80 }}>Outil</th>
                      <th>Alerte</th>
                      <th style={{ width: 90 }}>Depuis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {incident.alerts.map((alert) => (
                      <tr key={alert.key}>
                        <td>
                          <SeverityBadge severity={alert.severity} short source={alert.source_severity} tool={alert.tool} />
                        </td>
                        <td>
                          <ToolTag tool={alert.tool} />
                        </td>
                        <td className="wrap">
                          {alert.message}
                          {alert.key === incident.trigger?.key && (
                            <Badge color="var(--accent-ink)" className="ml-1.5">
                              à l'origine du ticket
                            </Badge>
                          )}
                        </td>
                        <td>{smartTime(alert.since)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          </div>
        </div>
      )}
    </Drawer>
  );
}

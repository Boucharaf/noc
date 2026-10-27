import { Link } from "react-router-dom";
import { Wrench } from "lucide-react";

import LocationLink from "./LocationLink";
import { Drawer } from "../ui/Overlay";
import { Badge, NodeStateBadge, SeverityBadge } from "../ui/Badge";
import { DefRow } from "../ui/Stat";
import { ErrorState, LoadingState } from "../ui/States";
import { dateTime, duration } from "../../lib/format";
import { toolLabel } from "../../lib/vocabulary";
import { useIncident } from "../../hooks/queries";

/**
 * Fiche d'une alerte d'outil de supervision — caractéristiques TECHNIQUES
 * uniquement.
 *
 * Aucun geste de traitement : ni acquittement, ni affectation, ni clôture.
 * Le traitement et les affectations sont tenus dans iTop (écran Incidents
 * iTop) ; le NOC montre ce que disent les outils, sans tenir un second
 * circuit de travail qui divergerait de l'ITSM.
 */
function Section({ title, aside, children }) {
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

export default function AlertDrawer({ alertKey, open, onClose }) {
  const query = useIncident(open ? alertKey : null);
  const alert = query.data;
  const node = alert?.node;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={560}
      title={alert ? alert.message || alert.description || alert.key : "Alerte"}
      badge={alert && <SeverityBadge severity={alert.severity} source={alert.source_severity} tool={alert.tool} />}
      subtitle={
        alert && (
          <span className="flex flex-wrap items-center gap-2">
            <span>{toolLabel(alert.tool)}</span>
            <span>· depuis {duration(alert.age_minutes)}</span>
            {alert.acknowledged && <Badge color="var(--accent-ink)">acquittée dans l'outil</Badge>}
            {alert.is_maintenance && (
              <Badge color="var(--state-maintenance)">
                <Wrench size={10} /> maintenance planifiée
              </Badge>
            )}
            {alert.cleared && <Badge color="var(--state-up)">close à la source</Badge>}
          </span>
        )
      }
    >
      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState error={query.error} onRetry={query.refetch} />}
      {alert && (
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Section title="Alerte">
            <DefRow label="Outil">{toolLabel(alert.tool)}</DefRow>
            <DefRow label="Référence" mono>{alert.ref ?? alert.key}</DefRow>
            <DefRow label={`Gravité ${toolLabel(alert.tool)}`}><SeverityBadge severity={alert.severity} source={alert.source_severity} tool={alert.tool} /></DefRow>
            <DefRow label="Type">
              {alert.kind === "manual_incident" ? "Signalement manuel" : "Alerte technique"}
            </DefRow>
            <DefRow label="Détectée le">{dateTime(alert.since)}</DefRow>
            <DefRow label="Durée">{duration(alert.age_minutes)}</DefRow>
            <DefRow label="Dernière lecture">{dateTime(alert.last_observed_at)}</DefRow>
            {alert.stale && (
              <DefRow label="Fraîcheur">
                <span style={{ color: "var(--sev-medium)" }}>
                  outil injoignable — dernière valeur connue
                </span>
              </DefRow>
            )}
            {alert.maintenance_reason && <DefRow label="Maintenance">{alert.maintenance_reason}</DefRow>}
            {alert.ticket_ref && <DefRow label="Ticket iTop" mono>{alert.ticket_ref}</DefRow>}
          </Section>

          <Section title="Localisation">
            <DefRow label="Lieu">
              <LocationLink
                site={node?.site ?? alert.site}
                province={node?.province ?? alert.province}
                region={node?.region ?? alert.region}
                position={alert.position}
                name={node?.name ?? alert.node_name}
              />
            </DefRow>
            <DefRow label="Organisation">{node?.organisation}</DefRow>
          </Section>

          <div className="sm:col-span-2">
            <Section
              title="Équipement"
              aside={
                node && (
                  <Link to={`/equipements/${encodeURIComponent(node.id)}`} className="btn btn-ghost btn-sm">
                    Fiche équipement ›
                  </Link>
                )
              }
            >
              {!node ? (
                <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {alert.node_name
                    ? `${alert.node_name} — absent de l'inventaire collecté.`
                    : "Aucun équipement rattaché à cette alerte."}
                </p>
              ) : (
                <div className="grid gap-x-4 sm:grid-cols-2">
                  <div>
                    <DefRow label="Nom">{node.name}</DefRow>
                    <DefRow label="Nom technique" mono>{node.hostname}</DefRow>
                    <DefRow label="Adresse IP" mono>{node.ip}</DefRow>
                    <DefRow label="Type">{node.node_type}</DefRow>
                  </div>
                  <div>
                    <DefRow label="État"><NodeStateBadge state={node.state} /></DefRow>
                    <DefRow label="Alertes actives">{node.alerts}</DefRow>
                    {Object.entries(node.sources).map(([tool, ref]) => (
                      <DefRow key={tool} label={`Réf. ${toolLabel(tool)}`} mono>
                        {ref}
                        {node.state_conflict?.[tool] && (
                          <span className="ml-1.5 text-[11px]" style={{ color: "var(--ink-3)" }}>
                            ({node.state_conflict[tool]})
                          </span>
                        )}
                      </DefRow>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          </div>
        </div>
      )}
    </Drawer>
  );
}

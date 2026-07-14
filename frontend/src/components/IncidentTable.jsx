import React from "react";
import Card from "./Card";
import { SeverityBadge, StatusBadge } from "./Badge";

const formatAge = (minutes) => {
  if (minutes == null) return "—";
  if (minutes < 60) return `il y a ${minutes} min`;
  if (minutes < 1440) return `il y a ${Math.round(minutes / 60)}h`;
  return `il y a ${Math.round(minutes / 1440)}j`;
};

const IncidentTable = ({
  title = "Liste des Incidents",
  incidents = [],
  loading = false,
  maxHeight = "clamp(280px, calc(100vh - 480px), 640px)",
}) => {
  const th = "sticky top-0 z-10 px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide border-b";
  const td = "px-4 py-3 text-sm whitespace-nowrap";
  const thStyle = { background: "var(--color-surface)", borderColor: "var(--color-border)" };

  return (
    <Card title={title} bodyClassName="p-0 ">
      {/* The scroll container must own both axes — a sticky <thead> only
          stays put relative to *this* element's scrolling, not the page's,
          and `overflow` set on <tbody> is a no-op (table-row-group ignores it). */}
      <div className="overflow-auto" style={{ maxHeight }}>
        <table className="w-full">
          <thead>
            <tr style={{ color: "var(--color-text-secondary)" }}>
              <th className={th} style={thStyle}>ID</th>
              <th className={th} style={thStyle}>Nœud</th>
              <th className={th} style={thStyle}>Sévérité</th>
              <th className={th} style={thStyle}>Statut</th>
              <th className={th} style={thStyle}>Description</th>
              <th className={th} style={thStyle}>Détection</th>
              <th className={th} style={thStyle}>Ticket iTop</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {loading && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-6 text-center text-sm"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  Chargement…
                </td>
              </tr>
            )}
            {!loading && incidents.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-4 py-6 text-center text-sm"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  Aucun incident.
                </td>
              </tr>
            )}
            {incidents.map((inc) => (
              <tr
                key={inc.id}
                className="border-t transition-colors hover:bg-[var(--color-surface-2)]"
                style={{ borderColor: "var(--color-border)" }}
              >
                <td
                  className={`${td} font-medium tabular-nums`}
                  style={{ color: "var(--color-text-primary)" }}
                >
                  #{inc.id}
                </td>
                <td
                  className={`${td} font-mono text-xs`}
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {inc.node_code}
                </td>
                <td className={td}>
                  <SeverityBadge severity={inc.severity} />
                </td>
                <td className={td}>
                  <StatusBadge status={inc.status} />
                </td>
                <td
                  className="max-w-xs truncate px-4 py-3 text-sm"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {inc.description}
                </td>
                <td className={td} style={{ color: "var(--color-text-muted)" }}>
                  {formatAge(inc.age_minutes)}
                </td>
                <td className={`${td} font-mono text-xs`} style={{ color: "var(--color-text-secondary)" }}>
                  {inc.itop_ticket_id ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
};

export default IncidentTable;

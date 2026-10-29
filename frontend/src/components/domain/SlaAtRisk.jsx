import { useState } from "react";

import ItopIncidentDrawer from "./ItopIncidentDrawer";
import Panel from "../ui/Panel";
import { QueryBoundary } from "../ui/States";
import { SeverityBadge } from "../ui/Badge";
import { duration, num } from "../../lib/format";
import { useSlaAtRisk } from "../../hooks/queries";

/**
 * Incidents iTop en danger de SLA : déjà hors délai, ou à moins de 25 % du
 * délai de résolution.
 *
 * Le seul indicateur d'engagement sur lequel on peut encore agir — les taux
 * de respect racontent le passé. Trié par marge restante, le plus urgent en
 * tête ; un clic ouvre la fiche du ticket.
 */
export default function SlaAtRisk({ limit = 8, className = "" }) {
  const query = useSlaAtRisk();
  const [selected, setSelected] = useState(null);
  const rows = query.data ?? [];
  const breached = rows.filter((row) => row.breached).length;

  return (
    <>
      <Panel
        title="SLA en danger"
        subtitle={
          rows.length
            ? `${num(breached)} hors délai · ${num(rows.length - breached)} à moins de 25 % du délai`
            : "incidents iTop proches de leur objectif de résolution"
        }
        accent={breached ? "var(--sev-critical)" : rows.length ? "var(--sev-medium)" : "var(--state-up)"}
        to="/incidents"
        toLabel="Incidents"
        className={className}
        flush
      >
        <QueryBoundary
          query={query}
          compact
          empty={(data) => !data?.length}
          emptyMessage="Aucun incident en danger de SLA"
          emptyHint="Les incidents ouverts sont tous dans leurs délais de résolution."
        >
          {() => (
            <ul className="divide-y" style={{ borderColor: "var(--border)" }}>
              {rows.slice(0, limit).map((row) => (
                <li key={row.key}>
                  <button
                    type="button"
                    onClick={() => setSelected(row.key)}
                    className="w-full text-left flex items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-2)]"
                  >
                    <SeverityBadge severity={row.severity} short />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12px] font-medium truncate" title={row.title}>
                        {row.ref ? `${row.ref} · ` : ""}
                        {row.title}
                      </span>
                      <span className="block text-[10.5px] truncate" style={{ color: "var(--ink-3)" }}>
                        {row.node_name || "CI non rattaché"}
                        {row.site ? ` · ${row.site}` : ""}
                        {" · "}
                        {row.agent || "non affecté"}
                      </span>
                    </span>
                    <span
                      className="num text-[11px] text-right"
                      style={{
                        color: row.breached ? "var(--sev-critical)" : "var(--sev-medium)",
                        minWidth: 74,
                      }}
                      title={`Objectif de résolution : ${duration(row.target_minutes)}`}
                    >
                      {row.breached
                        ? `+${duration(-row.remaining_minutes)}`
                        : `reste ${duration(row.remaining_minutes)}`}
                    </span>
                  </button>
                </li>
              ))}
              {rows.length > limit && (
                <li className="px-2.5 py-1 text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                  et {num(rows.length - limit)} autre(s)
                </li>
              )}
            </ul>
          )}
        </QueryBoundary>
      </Panel>
      <ItopIncidentDrawer
        incidentKey={selected}
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

import { Meter } from "../ui/Stat";
import { QueryBoundary, SkeletonRows } from "../ui/States";
import DataTable from "../ui/Table";
import { duration, num, pct } from "../../lib/format";
import { LEVEL } from "../../lib/locality";
import { complianceColor } from "../../lib/itop";

/**
 * Respect des SLA des incidents iTop, une ligne par région, province, site
 * ou équipement (GET /sla/incidents).
 *
 * Le taux n'est affiché que s'il porte sur au moins un incident évalué :
 * « 100 % » sur zéro incident n'est pas un résultat, c'est une absence.
 */
export default function SlaBreakdown({ query, groupBy, onSelect, maxHeight = 360 }) {
  const columns = [
    {
      key: "name",
      header: LEVEL[groupBy]?.label ?? "Périmètre",
      wrap: true,
      render: (row) => (
        <span>
          <span className="font-medium">{row.name}</span>
          {groupBy === "node" && row.site && (
            <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
              {[row.site, row.province, row.region].filter(Boolean).join(" · ")}
            </span>
          )}
        </span>
      ),
    },
    { key: "incidents", header: "Incidents", width: 74, align: "right", render: (r) => num(r.incidents) },
    { key: "resolved", header: "Résolus", width: 66, align: "right", render: (r) => num(r.resolved) },
    {
      key: "breached",
      header: "Dépassés",
      width: 72,
      align: "right",
      render: (r) => (
        <span style={{ color: r.breached ? "var(--sev-critical)" : undefined }}>{num(r.breached)}</span>
      ),
    },
    {
      key: "compliance",
      header: "Respect SLA",
      width: 150,
      render: (r) => (
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <Meter value={r.compliance_pct} color={complianceColor(r.compliance_pct)} />
          </div>
          <span className="num text-[11.5px]" style={{ color: complianceColor(r.compliance_pct), minWidth: 46 }}>
            {pct(r.compliance_pct, 1)}
          </span>
        </div>
      ),
    },
    { key: "mttr", header: "MTTR", width: 70, align: "right", render: (r) => duration(r.mttr_minutes) },
  ];

  return (
    <div style={{ maxHeight, overflow: "auto" }}>
      <QueryBoundary
        query={query}
        compact
        skeleton={<SkeletonRows rows={5} columns={6} />}
        empty={(data) => !data?.rows?.length}
        emptyMessage="Aucun incident iTop sur la période dans ce périmètre"
      >
        {(data) => (
          <DataTable
            dense
            columns={columns}
            rows={data.rows}
            rowKey={(row) => row.key}
            onRowClick={onSelect}
          />
        )}
      </QueryBoundary>
    </div>
  );
}

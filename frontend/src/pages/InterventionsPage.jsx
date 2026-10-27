import { Link, useSearchParams } from "react-router-dom";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import DataTable from "../components/ui/Table";
import { Badge } from "../components/ui/Badge";
import { SearchField, Segmented, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { dateTime, num } from "../lib/format";
import { useInterventions } from "../hooks/queries";
import { scopeLabel, useScopeStore } from "../store/scope";

/**
 * Interventions — ordres de travail iTop, en LECTURE SEULE.
 *
 * Une intervention est un ORDRE DE TRAVAIL rattaché au ticket qui l'a
 * motivée (incident, demande, changement). Son affectation (équipe, agent),
 * ses dates et sa clôture se tiennent dans iTop ; le NOC les montre à côté
 * de l'état de l'équipement concerné, sans tenir un second circuit.
 */
const STATUSES = [
  { value: "open", label: "Ouvertes" },
  { value: "closed", label: "Clôturées" },
  { value: "all", label: "Toutes" },
];

export default function InterventionsPage() {
  const [params, setParams] = useSearchParams();
  const scope = useScopeStore();
  const status = params.get("statut") || "open";
  const search = params.get("q") || "";
  const query = useInterventions(status);
  const data = query.data;

  const setParam = (key, value, fallback) => {
    const next = new URLSearchParams(params);
    if (value && value !== fallback) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const needle = search.trim().toLowerCase();
  const rows = (data?.work_orders ?? []).filter(
    (o) =>
      !needle ||
      [o.ref, o.title, o.agent, o.team, o.ticket?.ref, ...(o.nodes ?? []).map((n) => n.name)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
  );

  const columns = [
    {
      key: "status",
      header: "Statut",
      width: 96,
      render: (o) =>
        o.status === "closed" ? (
          <Badge color="var(--ink-3)">Clôturé</Badge>
        ) : (
          <Badge color="var(--accent-ink)">Ouvert</Badge>
        ),
    },
    { key: "title", header: "Ordre de travail", wrap: true, render: (o) => <span className="font-medium">{o.title}</span> },
    {
      key: "ticket",
      header: "Ticket iTop",
      width: 200,
      wrap: true,
      render: (o) =>
        o.ticket ? (
          <span className="text-[12px]">
            <span className="num">{o.ticket.ref ?? "—"}</span>
            {o.ticket.title && (
              <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                {o.ticket.title}
              </span>
            )}
          </span>
        ) : (
          <span style={{ color: "var(--ink-3)" }}>—</span>
        ),
    },
    {
      key: "where",
      header: "Équipement · localité",
      wrap: true,
      render: (o) =>
        o.nodes_total ? (
          <span className="text-[12px]">
            {o.nodes.slice(0, 2).map((node, index) => (
              <span key={node.id}>
                {index > 0 && ", "}
                <Link to={`/equipements/${encodeURIComponent(node.id)}`} style={{ color: "var(--accent-ink)" }}>
                  {node.name}
                </Link>
              </span>
            ))}
            {o.nodes_total > 2 && ` + ${num(o.nodes_total - 2)}`}
            <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
              {[o.nodes[0]?.site, o.nodes[0]?.province, o.nodes[0]?.region].filter(Boolean).join(" · ")}
            </span>
          </span>
        ) : (
          <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            {o.cis?.length ? "CI non retrouvé dans la supervision" : "aucun CI sur le ticket"}
          </span>
        ),
    },
    {
      key: "who",
      header: "Équipe · agent",
      width: 170,
      render: (o) =>
        o.agent || o.team ? (
          [o.team, o.agent].filter(Boolean).join(" · ")
        ) : (
          <span style={{ color: "var(--sev-high)" }}>non affecté</span>
        ),
    },
    {
      key: "dates",
      header: "Début → fin",
      width: 220,
      render: (o) => (
        <span className="num text-[11.5px]">
          {dateTime(o.start)} → {o.end ? dateTime(o.end) : "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-2">
      <PageHeader
        title="Interventions"
        subtitle={`Ordres de travail iTop — ${scopeLabel(scope)}`}
        actions={
          <Segmented ariaLabel="Statut" options={STATUSES} value={status} onChange={(v) => setParam("statut", v, "open")} />
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        <Stat label="Ouvertes" value={num(data?.counts?.open)} />
        <Stat
          label="Non affectées"
          value={num(data?.counts?.unassigned)}
          color={data?.counts?.unassigned ? "var(--sev-high)" : undefined}
        />
        <Stat label="Clôturées (30 j)" value={num(data?.counts?.closed)} />
      </div>

      <Panel title="Ordres de travail" flush>
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                <span className="num" style={{ color: "var(--ink-2)" }}>{num(rows.length)}</span> intervention(s)
              </span>
            }
          >
            <SearchField
              value={search}
              onChange={(value) => setParam("q", value)}
              placeholder="Ordre, ticket, équipement, agent…"
              width={240}
              suggest="intervention"
            />
          </Toolbar>
        </div>
        <QueryBoundary
          query={query}
          skeleton={<SkeletonRows rows={6} columns={6} />}
          empty={() => rows.length === 0}
          emptyMessage="Aucune intervention dans ce périmètre"
          emptyHint="Les ordres de travail se créent et se suivent dans iTop."
        >
          {() => <DataTable columns={columns} rows={rows} rowKey={(o) => o.key} />}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

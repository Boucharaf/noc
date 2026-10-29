import { useSearchParams } from "react-router-dom";

import Panel from "../components/ui/Panel";
import DataTable, { Pagination } from "../components/ui/Table";
import { Badge } from "../components/ui/Badge";
import { FilterSelect, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { dateTime, num } from "../lib/format";
import { useAuditLog } from "../hooks/queries";

/**
 * Journal d'audit — qui a fait quoi, quand, depuis où.
 *
 * Connexions (réussies et refusées), comptes créés, modifiés ou désactivés,
 * mots de passe et PIN fixés, sessions coupées, objectifs SLA modifiés.
 * Lecture seule : chaque action écrit sa ligne côté serveur
 * (app/services/audit_service.py), et le journal ne se modifie pas.
 */
const PAGE_SIZE = 100;

const TONE = {
  "auth.login_failed": "var(--sev-high)",
  "auth.pin_login_failed": "var(--sev-high)",
  "user.deactivated": "var(--sev-medium)",
  "auth.sessions_revoked": "var(--sev-medium)",
};

/** Détail lisible : champs modifiés, changements « avant → après ». */
function describe(detail) {
  const parts = [];
  for (const [key, value] of Object.entries(detail ?? {})) {
    if (key === "user_id") continue;
    if (key === "fields") {
      if (value?.length) parts.push(`champs : ${value.join(", ")}`);
    } else if (value && typeof value === "object" && "from" in value) {
      parts.push(`${key} : ${value.from ?? "—"} → ${value.to ?? "—"}`);
    } else {
      parts.push(`${key} : ${value}`);
    }
  }
  return parts.join(" · ");
}

export default function AuditPage() {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page")) || 1);
  const action = params.get("action") || undefined;
  const query = useAuditLog({ action, limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE });
  const data = query.data;

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const columns = [
    {
      key: "at",
      header: "Date",
      width: 150,
      render: (entry) => <span className="num text-[11.5px]">{dateTime(entry.at)}</span>,
    },
    {
      key: "action",
      header: "Action",
      width: 190,
      render: (entry) => (
        <Badge color={TONE[entry.action] ?? "var(--accent-ink)"}>{entry.label}</Badge>
      ),
    },
    {
      key: "user",
      header: "Auteur",
      width: 160,
      render: (entry) =>
        entry.user ?? <span style={{ color: "var(--ink-3)" }}>non identifié</span>,
    },
    {
      key: "target",
      header: "Cible",
      width: 160,
      render: (entry) => entry.target ?? <span style={{ color: "var(--ink-3)" }}>—</span>,
    },
    {
      key: "detail",
      header: "Détail",
      wrap: true,
      render: (entry) => (
        <span className="text-[11.5px]" style={{ color: "var(--ink-2)" }}>
          {describe(entry.detail) || "—"}
        </span>
      ),
    },
    {
      key: "ip",
      header: "Adresse",
      width: 130,
      render: (entry) => <span className="num text-[11.5px]">{entry.ip ?? "—"}</span>,
    },
  ];

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Journal d'audit"
        subtitle="Connexions, comptes et objectifs SLA — qui a fait quoi, quand, depuis où"
        actions={
          <Toolbar>
            <FilterSelect
              label="Action"
              value={action}
              onChange={(value) => setParam("action", value)}
              allLabel="Toutes les actions"
              width={220}
              options={data?.actions ?? []}
            />
          </Toolbar>
        }
      />

      <Panel
        title="Entrées"
        subtitle={data ? `${num(data.total)} au total` : undefined}
        flush
      >
        <QueryBoundary
          query={query}
          skeleton={<SkeletonRows rows={10} columns={6} />}
          empty={(d) => !d?.entries?.length}
          emptyMessage="Aucune entrée"
          emptyHint="Les actions sensibles (connexions, comptes, objectifs SLA) apparaissent ici dès qu'elles ont lieu."
        >
          {(d) => (
            <>
              <DataTable columns={columns} rows={d.entries} />
              <Pagination
                page={page}
                pages={Math.max(1, Math.ceil(d.total / PAGE_SIZE))}
                total={d.total}
                pageSize={PAGE_SIZE}
                onChange={(next) => setParam("page", next > 1 ? String(next) : null)}
                label="entrées"
              />
            </>
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

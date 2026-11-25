import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useWindowStore, windowDays } from "../store/ui";

import ItopIncidentDrawer from "../components/domain/ItopIncidentDrawer";
import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import DataTable, { Pagination } from "../components/ui/Table";
import { Badge, SeverityBadge } from "../components/ui/Badge";
import { FilterSelect, Notice, SearchField, Tabs, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { dateTime, duration, num, pct } from "../lib/format";
import { ITOP_STATUS, itopStatusMeta, slaStatusMeta } from "../lib/itop";
import { SEVERITIES, severityMeta } from "../lib/vocabulary";
import {
  useItopIncidentHistory,
  useItopIncidents,
  useLiveTrend,
  useSlaIncidents,
} from "../hooks/queries";
import { scopeLabel, useScopeStore } from "../store/scope";

/**
 * Incidents — tickets iTop UNIQUEMENT.
 *
 * Les alertes des outils (Zabbix, NetXMS…) ont leur propre écran. Chaque
 * ligne ici est un ticket iTop ouvert, rattaché à son équipement et à sa
 * localité ; la colonne « Alertes » dit combien de signaux techniques des
 * outils l'accompagnent, et la fiche les détaille.
 *
 * Deux onglets : « En cours » (instantané) et « Historique » (tickets
 * ouverts sur la période, clos ou non, lus chez iTop). Les deux sont
 * paginés côté serveur ; les compteurs portent sur l'ensemble filtré.
 *
 * Filtres et page dans l'URL (partage d'une file, F5), périmètre dans la
 * barre commune.
 */
const PAGE_SIZE = 50;
const CLOSED = ["resolved", "closed", "rejected"];

/**
 * Barres horizontales d'une répartition. `part` (facultatif) colore la part
 * « grave » de chaque barre — ici les tickets déjà hors délai.
 */
function Bars({ rows, onSelect, selected, partLabel }) {
  const max = Math.max(1, ...rows.map((row) => row.count));
  return (
    <ul className="space-y-1.5">
      {rows.map((row) => {
        const active = selected && selected === row.key;
        const content = (
          <>
            <div className="flex items-baseline gap-2 text-[12px]">
              <span className="flex-1 truncate" style={{ fontWeight: active ? 600 : undefined }}>
                {row.label}
              </span>
              {row.part > 0 && (
                <span className="text-[12px]" style={{ color: "var(--sev-critical)" }}>
                  {num(row.part)} {partLabel}
                </span>
              )}
              <span className="num" style={{ minWidth: 34, textAlign: "right" }}>{num(row.count)}</span>
            </div>
            <div className="relative h-[7px] rounded-full mt-1" style={{ background: "var(--surface-3)" }}>
              <div
                className="absolute left-0 top-0 bottom-0 rounded-full"
                style={{ width: `${(100 * row.count) / max}%`, background: row.color ?? "var(--accent)" }}
              />
              {row.part > 0 && (
                <div
                  className="absolute left-0 top-0 bottom-0 rounded-full"
                  style={{ width: `${(100 * row.part) / max}%`, background: "var(--sev-critical)" }}
                />
              )}
            </div>
          </>
        );
        return (
          <li key={row.key}>
            {onSelect ? (
              <button
                type="button"
                className="w-full text-left"
                onClick={() => onSelect(active ? null : row.key)}
                title={active ? "Retirer le filtre" : `Filtrer : ${row.label}`}
              >
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ul>
  );
}

// Plus un ticket ouvert est vieux, plus la couleur est chaude.
const AGE_COLORS = {
  lt4h: "var(--state-up)",
  lt24h: "var(--accent)",
  lt7d: "var(--sev-medium)",
  lt30d: "var(--sev-high)",
  gt30d: "var(--sev-critical)",
};

export default function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const scope = useScopeStore();
  const selected = params.get("id");
  const view = params.get("vue") === "historique" ? "history" : "open";
  const page = Math.max(1, Number(params.get("page")) || 1);
  // Historique : période globale de la barre unique (INC-28), en jours.
  const days = windowDays(useWindowStore((s) => s.hours));
  // AM-20 : temps moyen par étape du circuit, sur l'historique iTop de la
  // période (mêmes tickets que l'écran SLA).
  const stages = useSlaIncidents({ days }).data?.totals;

  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    // Un filtre qui change ramène en première page ; ouvrir une fiche, non.
    if (key !== "page" && key !== "id") next.delete("page");
    setParams(next, { replace: true });
  };

  const filters = useMemo(() => {
    const value = {
      severity: params.get("severity") || undefined,
      status: params.get("status") || undefined,
    };
    // La recherche de l'écran l'emporte sur celle de la barre commune.
    if (params.get("q")) value.search = params.get("q");
    return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined));
  }, [params]);

  const offset = (page - 1) * PAGE_SIZE;
  const query = useItopIncidents(
    view === "open" ? { ...filters, offset, limit: PAGE_SIZE } : { ...filters, limit: 1 },
  );
  const data = query.data;
  const trend = useLiveTrend();
  const history = useItopIncidentHistory(
    view === "history" ? { ...filters, days, offset, limit: PAGE_SIZE } : null,
  );
  const listQuery = view === "open" ? query : history;
  const listTotal = listQuery.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(listTotal / PAGE_SIZE));

  const columns = [
    {
      key: "severity",
      header: "Gravité",
      width: 96,
      render: (row) => <SeverityBadge severity={row.severity} short />,
    },
    {
      key: "ref",
      header: "Réf.",
      width: 92,
      mono: true,
      render: (row) => row.ref ?? row.key,
    },
    { key: "title", header: "Incident", wrap: true, render: (row) => row.title },
    {
      key: "where",
      header: "Équipement · localité",
      wrap: true,
      render: (row) => (
        <span>
          <span className="font-medium">{row.node_name ?? "CI non rattaché"}</span>
          <span className="block text-[12px]" style={{ color: "var(--ink-3)" }}>
            {[row.site, row.province, row.region].filter(Boolean).join(" · ") || "localité inconnue"}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Statut",
      width: 120,
      render: (row) => {
        const meta = itopStatusMeta(row.status);
        return <Badge color={meta.color}>{meta.label}</Badge>;
      },
    },
    {
      key: "agent",
      header: "Pris en charge par",
      width: 150,
      render: (row) =>
        row.agent ?? <span style={{ color: "var(--sev-high)" }}>non affecté</span>,
    },
    {
      key: "age",
      header: "Âge",
      width: 70,
      align: "right",
      render: (row) => duration(row.age_minutes),
    },
    {
      key: "sla",
      header: "SLA",
      width: 112,
      render: (row) => {
        const meta = slaStatusMeta(row.sla?.ttr_status);
        return <Badge color={meta.color}>{meta.label}</Badge>;
      },
    },
    {
      key: "alerts",
      header: "Alertes",
      width: 66,
      align: "right",
      render: (row) => (
        <span
          className="num"
          style={{ color: row.related_alerts_critical ? "var(--sev-critical)" : undefined }}
          title="Alertes techniques des outils sur l'équipement"
        >
          {num(row.related_alerts)}
        </span>
      ),
    },
  ];

  const historyColumns = [
    columns[0],
    columns[1],
    columns[2],
    columns[3],
    columns[4],
    {
      key: "opened_at",
      header: "Ouvert le",
      width: 120,
      mono: true,
      render: (row) => dateTime(row.opened_at),
    },
    {
      key: "resolved_at",
      header: "Résolu",
      width: 120,
      render: (row) =>
        row.resolved_at ? (
          <span>
            <span className="num">{dateTime(row.resolved_at)}</span>
            <span className="block text-[12px]" style={{ color: "var(--ink-3)" }}>
              en {duration(row.sla?.ttr_minutes)}
            </span>
          </span>
        ) : (
          <span style={{ color: "var(--ink-3)" }}>non résolu</span>
        ),
    },
    columns[7],
    { ...columns[5], header: "Agent" },
  ];

  return (
    <div className="space-y-2">
      <PageHeader
        title="Incidents iTop"
        subtitle={`Tickets ouverts dans iTop — ${scopeLabel(scope)}`}
      />

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          sources="incidents"
          label="Incidents ouverts"
          value={num(data?.total)}
          spark={trend.data?.incidents}
          invertDelta
          help="Tickets iTop non résolus et non clos. La courbe montre leur nombre sur les dernières 24 h."
        />
        <Stat
          label="Critiques"
          value={num(data?.by_severity?.critical)}
          color={data?.by_severity?.critical ? "var(--sev-critical)" : undefined}
        />
        <Stat
          label="Haute priorité"
          value={num(data?.by_severity?.high)}
          color={data?.by_severity?.high ? "var(--sev-high)" : undefined}
        />
        <Stat
          label="Non affectés"
          value={num(data?.unassigned)}
          color={data?.unassigned ? "var(--sev-high)" : undefined}
        />
        <Stat
          label="SLA dépassé"
          // INC-38 : pas de « hors délai » affirmé sur des données iTop
          // périmées ou sans objectif de délai.
          value={data && !data.sla_evaluable ? "Non évaluable" : num(data?.sla_breached)}
          color={
            data && !data.sla_evaluable
              ? "var(--ink-3)"
              : data?.sla_breached
                ? "var(--sev-critical)"
                : "var(--state-up)"
          }
          hint={
            data && !data.sla_evaluable
              ? data.itop_stale
                ? "iTop indisponible : délais non vérifiables"
                : "aucun ticket avec objectif de délai"
              : data && `sur ${num(data.sla_evaluated)} ticket(s) avec objectif`
          }
          help="Tickets ouverts dont le délai de résolution (TTR) est déjà dépassé, parmi ceux qui ont un objectif de délai. Non évaluable si iTop ne répond pas."
        />
        <Stat
          label="Rattachés à un équipement"
          value={pct(data?.attachment_rate_pct, 0)}
          target="≥ 95 %"
          color={
            data?.attachment_rate_pct == null
              ? undefined
              : data.attachment_rate_pct >= 95
                ? "var(--state-up)"
                : data.attachment_rate_pct >= 80
                  ? "var(--sev-medium)"
                  : "var(--sev-critical)"
          }
          hint={data && `${num(data.network_unlocated)} ticket(s) sans équipement`}
          help="Part des tickets iTop ouverts liés à un équipement (CI iTop, ou équipement cité dans le titre). Un ticket non rattaché ne peut être placé ni sur la carte, ni dans une région."
        />
      </div>

      {/* D'où viennent les écarts de comptage quand on filtre : un ticket iTop
          n'a pas de localité propre ; il n'est situé que par l'équipement
          concerné (CI lié, ou équipement cité dans le titre). */}
      {view === "open" && data && (
        <div className="grid grid-cols-12 gap-2 items-start">
          <Panel
            title="Ancienneté des tickets ouverts"
            subtitle="en rouge : déjà hors délai (SLA)"
            className="col-span-12 lg:col-span-6"
          >
            <Bars
              rows={(data.age_buckets ?? []).map((bucket) => ({
                key: bucket.key,
                label: bucket.label,
                count: bucket.count,
                part: bucket.breached,
                color: AGE_COLORS[bucket.key],
              }))}
              partLabel="hors délai"
            />
          </Panel>
          <Panel
            title="Circuit de traitement"
            subtitle={
              stages && (stages.mtto_minutes != null || stages.mttr_minutes != null)
                ? `Nouveau → Affecté : ${duration(stages.mtto_minutes)} en moyenne · Affecté → Résolu : ${duration(
                    stages.mttr_minutes != null && stages.mtto_minutes != null
                      ? Math.max(0, stages.mttr_minutes - stages.mtto_minutes)
                      : null,
                  )} · clic pour filtrer`
                : "où en sont les tickets · clic pour filtrer"
            }
            className="col-span-12 lg:col-span-6"
          >
            <Bars
              rows={(data.by_status ?? []).map((row) => ({
                key: row.status,
                label: itopStatusMeta(row.status).label,
                count: row.count,
                color: itopStatusMeta(row.status).color,
              }))}
              selected={params.get("status")}
              onSelect={(status) => setParam("status", status)}
            />
          </Panel>
        </div>
      )}

      {view === "open" && data?.scoped && (
        <Notice tone="info">
          <strong>{num(data.total)}</strong> incident(s) dans ce périmètre, sur{" "}
          <strong>{num(data.network_total)}</strong> tickets ouverts dans iTop.{" "}
          {data.network_unlocated > 0 && (
            <>
              <strong>{num(data.network_unlocated)}</strong> ticket(s) ne sont liés à aucun
              équipement : ils ne peuvent pas être placés sur la carte, et ne sont visibles
              qu'avec « Tout le réseau ». Pour les corriger, liez le ticket à son équipement
              (CI) dans iTop.
            </>
          )}
        </Notice>
      )}

      {view === "open" && data && (
        <div className="grid grid-cols-12 gap-2 items-start">
          <Panel
            title="Tickets iTop par région"
            // INC-11 : les parts régionales sont calculées sur les tickets
            // LOCALISABLES ; les non localisés sont comptés à part.
            subtitle={`% sur ${num(data.network_located)} tickets localisables · ${num(
              data.network_unlocated,
            )} non localisé(s) · clic pour filtrer`}
            className="col-span-12 lg:col-span-6"
          >
            <ul className="space-y-1">
              {data.network_by_region.map((row) => {
                const unknown = row.region.endsWith("non renseignée");
                const active = scope.region === row.region;
                return (
                  <li key={row.region}>
                    <button
                      type="button"
                      disabled={unknown}
                      onClick={() => scope.setRegion(active ? null : row.region)}
                      className="w-full text-left"
                      title={
                        unknown
                          ? "Tickets sans équipement identifiable : pas de localité"
                          : `Filtrer sur ${row.region}`
                      }
                    >
                      <div className="flex items-baseline gap-2 text-[12px]">
                        <span
                          className="flex-1 truncate"
                          style={{
                            color: unknown ? "var(--ink-3)" : active ? "var(--accent-ink)" : undefined,
                            fontStyle: unknown ? "italic" : undefined,
                            fontWeight: active ? 600 : undefined,
                          }}
                        >
                          {unknown ? "Non localisés (aucun équipement lié)" : row.region}
                        </span>
                        <span className="num">{num(row.count)}</span>
                        <span className="num" style={{ width: 44, textAlign: "right", color: "var(--ink-3)" }}>
                          {unknown || !data.network_located
                            ? ""
                            : pct((100 * row.count) / data.network_located, 0)}
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>
          <Panel
            title="Par organisation"
            subtitle={data.scoped ? "tickets du périmètre" : "tous les tickets ouverts"}
            className="col-span-12 lg:col-span-6"
          >
            {data.by_organisation.length === 0 ? (
              <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                Aucun ticket dans ce périmètre.
              </p>
            ) : (
              <ul className="space-y-1">
                {data.by_organisation.map((row) => (
                  <li key={row.organisation} className="flex items-baseline gap-2 text-[12px]">
                    <span className="flex-1 truncate" title={row.organisation}>
                      {row.organisation}
                    </span>
                    <span className="num">{num(row.count)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}

      <Panel title="Incidents iTop" flush>
        <div className="px-2 pt-1">
          <Tabs
            value={view}
            onChange={(value) => {
              const next = new URLSearchParams(params);
              if (value === "history") next.set("vue", "historique");
              else next.delete("vue");
              next.delete("page");
              next.delete("status");
              setParams(next, { replace: true });
            }}
            tabs={[
              { value: "open", label: "En cours", count: view === "open" ? data?.total : undefined },
              {
                value: "history",
                label: "Historique",
                count: view === "history" ? history.data?.total : undefined,
              },
            ]}
          />
        </div>
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                <span className="num" style={{ color: "var(--ink-2)" }}>
                  {num(listTotal)}
                </span>{" "}
                {view === "open" ? "incident(s) ouvert(s)" : `ticket(s) ouverts sur ${days} jours`}
                {view === "history" && history.data && (
                  <>
                    {" · "}
                    <span className="num">{num(history.data.resolved)}</span> résolu(s) ·{" "}
                    <span
                      className="num"
                      style={{ color: history.data.sla_breached ? "var(--sev-critical)" : undefined }}
                    >
                      {num(history.data.sla_breached)}
                    </span>{" "}
                    SLA dépassé(s)
                  </>
                )}
              </span>
            }
          >
            <SearchField
              value={params.get("q") ?? ""}
              onChange={(value) => setParam("q", value)}
              placeholder="Réf., titre, équipement, agent…"
              width={230}
              suggest="incident"
            />
            <FilterSelect
              label="Gravité"
              value={params.get("severity")}
              onChange={(value) => setParam("severity", value)}
              allLabel="Toute gravité"
              width={140}
              options={SEVERITIES.filter((s) => s !== "unknown").map((severity) => ({
                value: severity,
                label: severityMeta(severity).label,
              }))}
            />
            <FilterSelect
              label="Statut"
              value={params.get("status")}
              onChange={(value) => setParam("status", value)}
              allLabel="Tout statut"
              width={170}
              options={Object.entries(ITOP_STATUS)
                .filter(([status]) => view === "history" || !CLOSED.includes(status))
                .map(([status, meta]) => ({ value: status, label: meta.label }))}
            />
          </Toolbar>
        </div>
        <div style={{ maxHeight: "calc(var(--vh) - 300px)", overflow: "auto" }}>
          <QueryBoundary
            query={listQuery}
            skeleton={<SkeletonRows rows={10} columns={8} />}
            empty={(d) => !d?.incidents?.length}
            emptyMessage={
              view === "open"
                ? "Aucun incident iTop ouvert dans ce périmètre"
                : "Aucun ticket iTop sur la période dans ce périmètre"
            }
            emptyHint="Les alertes des outils de supervision sont dans l'écran « Alertes outils »."
          >
            {(d) => (
              <DataTable
                columns={view === "open" ? columns : historyColumns}
                rows={d.incidents}
                rowKey={(row) => row.key}
                selectedKey={selected}
                // Seuls les tickets encore ouverts ont une fiche : elle lit
                // l'instantané, qui ne contient pas les tickets clos.
                onRowClick={(row) =>
                  view === "open" || !CLOSED.includes(row.status)
                    ? setParam("id", row.key)
                    : undefined
                }
              />
            )}
          </QueryBoundary>
        </div>
        <Pagination
          page={Math.min(page, pages)}
          pages={pages}
          total={listTotal}
          pageSize={PAGE_SIZE}
          onChange={(next) => setParam("page", next > 1 ? String(next) : null)}
          label={view === "open" ? "incidents" : "tickets"}
        />
      </Panel>

      <ItopIncidentDrawer
        incidentKey={selected}
        open={Boolean(selected)}
        onClose={() => setParam("id", null)}
      />
    </div>
  );
}

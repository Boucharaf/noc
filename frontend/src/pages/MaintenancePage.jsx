import { useSearchParams } from "react-router-dom";
import { Link } from "react-router-dom";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import DataTable from "../components/ui/Table";
import { Badge } from "../components/ui/Badge";
import { SearchField, Segmented, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { dateTime, duration, num } from "../lib/format";
import { CHANGE_STATUS, changeStatusMeta } from "../lib/itop";
import { useMaintenanceWindows } from "../hooks/queries";
import { scopeLabel, useScopeStore } from "../store/scope";

/**
 * Maintenances planifiées — lues dans iTop et Zabbix, en LECTURE SEULE.
 *
 * Une maintenance se planifie là où l'agence la décide : un CHANGEMENT iTop
 * (dates de début et de fin, CI impactés), ou une maintenance Zabbix. Le NOC
 * les relit à chaque cycle de collecte et en tire deux effets :
 *   * les équipements visés passent à l'état « maintenance » pendant la
 *     fenêtre ;
 *   * leurs alertes sont marquées et sortent de la disponibilité et des SLA
 *     — une coupure voulue n'est pas une panne.
 */
const SCOPES = [
  { value: "all", label: "Toutes" },
  { value: "active", label: "En cours" },
  { value: "upcoming", label: "À venir" },
  { value: "past", label: "Terminées" },
];

const TIMING = {
  active: { label: "En cours", color: "var(--state-maintenance)" },
  upcoming: { label: "À venir", color: "var(--accent-ink)" },
  past: { label: "Terminée", color: "var(--ink-3)" },
};

const SOURCE = { change: "Changement iTop", maintenance: "Maintenance Zabbix" };

/**
 * Frise des maintenances : une ligne par fenêtre, une barre du début à la
 * fin, et le trait « maintenant ». Les chevauchements (deux coupures sur le
 * même site) et ce qui arrive dans les prochains jours se voient sans lire
 * de dates.
 */
function MaintenanceTimeline({ windows }) {
  const now = Date.now();
  const day = 86400_000;
  const starts = windows.map((w) => Date.parse(w.start)).filter(Number.isFinite);
  const ends = windows.map((w) => (w.end ? Date.parse(w.end) : now + 2 * day)).filter(Number.isFinite);
  const from = Math.min(now - day, ...starts);
  const to = Math.max(now + day, ...ends);
  const span = to - from || 1;
  const x = (t) => `${(100 * (t - from)) / span}%`;
  const ticks = [];
  for (let t = Math.ceil(from / day) * day; t <= to; t += day * Math.max(1, Math.round(span / day / 8))) {
    ticks.push(t);
  }
  return (
    <div className="relative" style={{ paddingTop: 18 }}>
      {ticks.map((t) => (
        <div key={t} className="absolute top-0 bottom-0" style={{ left: x(t), borderLeft: "1px dashed var(--border)" }}>
          <span className="absolute text-[10px] num -translate-x-1/2" style={{ top: -2, color: "var(--ink-3)" }}>
            {new Date(t).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" })}
          </span>
        </div>
      ))}
      <div
        className="absolute top-0 bottom-0 z-10"
        style={{ left: x(now), borderLeft: "2px solid var(--sev-critical)" }}
        title="Maintenant"
      />
      <ul className="relative space-y-1.5">
        {windows.map((w) => {
          const start = Date.parse(w.start);
          const end = w.end ? Date.parse(w.end) : to;
          // Libellé À CÔTÉ de la barre, jamais rogné : une coupure de 2 h sur
          // une frise de plusieurs jours n'a pas la place de porter son titre.
          // Il passe à gauche de la barre quand elle est trop à droite.
          const alignRight = (end - from) / span > 0.7;
          return (
            <li key={w.key} className="relative h-[22px]">
              <div
                className="absolute top-[3px] bottom-[3px] rounded"
                style={{
                  left: x(start),
                  width: `max(6px, calc(${x(end)} - ${x(start)}))`,
                  background: `color-mix(in srgb, ${TIMING[w.timing]?.color} 35%, transparent)`,
                  border: `1px solid ${TIMING[w.timing]?.color}`,
                  borderRightStyle: w.end ? "solid" : "dashed",
                }}
                title={`${w.title} — ${dateTime(w.start)} → ${w.end ? dateTime(w.end) : "non bornée"}`}
              />
              <span
                className="absolute top-0 bottom-0 flex items-center text-[11px] whitespace-nowrap px-1.5"
                style={
                  alignRight
                    ? { right: `calc(100% - ${x(start)})` }
                    : { left: `calc(${x(end)} + 2px)` }
                }
              >
                {w.kind === "change" && w.ref ? `${w.ref} · ` : ""}
                {w.title}
                {w.nodes_total ? ` · ${num(w.nodes_total)} équip.` : ""}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function MaintenancePage() {
  const [params, setParams] = useSearchParams();
  const scope = useScopeStore();
  const filter = params.get("vue") || "all";
  const search = params.get("q") || "";
  const query = useMaintenanceWindows(filter);
  const data = query.data;

  const setParam = (key, value, fallback) => {
    const next = new URLSearchParams(params);
    if (value && value !== fallback) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const needle = search.trim().toLowerCase();
  const rows = (data?.windows ?? []).filter(
    (w) =>
      !needle ||
      [w.ref, w.title, w.agent, w.team, ...(w.nodes ?? []).map((n) => n.name)]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
  );

  const columns = [
    {
      key: "timing",
      header: "Fenêtre",
      width: 96,
      render: (w) => <Badge color={TIMING[w.timing]?.color}>{TIMING[w.timing]?.label}</Badge>,
    },
    {
      key: "title",
      header: "Maintenance",
      wrap: true,
      render: (w) => (
        <span>
          <span className="font-medium">{w.title}</span>
          <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
            {SOURCE[w.kind] ?? w.tool}
            {w.kind === "change" && w.ref ? ` ${w.ref}` : ""}
            {w.change_type ? ` · ${w.change_type.replace("Change", "")}` : ""}
            {w.outage === true ? " · avec interruption de service" : ""}
          </span>
        </span>
      ),
    },
    {
      key: "status",
      header: "Statut",
      width: 120,
      render: (w) => {
        if (!w.status) return <span style={{ color: "var(--ink-3)" }}>—</span>;
        const meta = changeStatusMeta(w.status);
        return <Badge color={meta.color}>{meta.label}</Badge>;
      },
    },
    {
      key: "dates",
      header: "Début → fin",
      width: 230,
      render: (w) => (
        <span className="num text-[11.5px]">
          {dateTime(w.start)} → {w.end ? dateTime(w.end) : "non bornée"}
          {w.start && w.end && (
            <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
              durée {duration((new Date(w.end) - new Date(w.start)) / 60000)}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "nodes",
      header: "Équipements visés",
      wrap: true,
      render: (w) =>
        w.nodes_total ? (
          <span className="text-[12px]">
            {w.nodes.slice(0, 3).map((node, index) => (
              <span key={node.id}>
                {index > 0 && ", "}
                <Link
                  to={`/equipements/${encodeURIComponent(node.id)}`}
                  style={{ color: "var(--accent-ink)" }}
                  onClick={(event) => event.stopPropagation()}
                >
                  {node.name}
                </Link>
              </span>
            ))}
            {w.nodes_total > 3 && ` + ${num(w.nodes_total - 3)}`}
            {w.sites?.length > 0 && (
              <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                {w.sites.slice(0, 3).join(" · ")}
                {w.sites.length > 3 ? " …" : ""}
              </span>
            )}
          </span>
        ) : (
          <span className="text-[11.5px]" style={{ color: "var(--sev-medium)" }}>
            {w.cis?.length
              ? `${num(w.cis.length)} CI non retrouvé(s) dans la supervision`
              : "aucun CI rattaché"}
          </span>
        ),
    },
    {
      key: "who",
      header: "Responsable",
      width: 150,
      render: (w) =>
        [w.agent, w.team].filter(Boolean).join(" · ") || <span style={{ color: "var(--ink-3)" }}>—</span>,
    },
  ];

  return (
    <div className="space-y-2">
      <PageHeader
        title="Maintenances planifiées"
        subtitle={`Changements iTop et maintenances Zabbix — ${scopeLabel(scope)}`}
        actions={
          <Segmented ariaLabel="Fenêtre" options={SCOPES} value={filter} onChange={(v) => setParam("vue", v, "all")} />
        }
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <Stat
          label="En cours"
          value={num(data?.counts?.active)}
          color={data?.counts?.active ? "var(--state-maintenance)" : undefined}
        />
        <Stat label="À venir" value={num(data?.counts?.upcoming)} />
        <Stat label="Terminées (30 j)" value={num(data?.counts?.past)} />
        <Stat
          label="Équipements en maintenance"
          value={num(data?.nodes_in_maintenance)}
          hint="neutralisés dans les KPI"
        />
      </div>

      {rows.length > 0 && (
        <Panel title="Frise" subtitle="trait rouge : maintenant · bord pointillé : fin non bornée">
          <MaintenanceTimeline windows={rows} />
        </Panel>
      )}

      <Panel title="Fenêtres" flush>
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                <span className="num" style={{ color: "var(--ink-2)" }}>{num(rows.length)}</span> maintenance(s)
              </span>
            }
          >
            <SearchField
              value={search}
              onChange={(value) => setParam("q", value)}
              placeholder="Réf., titre, équipement, équipe…"
              width={240}
              suggest="maintenance"
            />
          </Toolbar>
        </div>
        <QueryBoundary
          query={query}
          skeleton={<SkeletonRows rows={6} columns={6} />}
          empty={() => rows.length === 0}
          emptyMessage="Aucune maintenance dans ce périmètre"
          emptyHint="Les maintenances se planifient dans iTop (changement) ou dans Zabbix."
        >
          {() => <DataTable columns={columns} rows={rows} rowKey={(w) => w.key} />}
        </QueryBoundary>
      </Panel>

      <p className="text-[11px] px-1" style={{ color: "var(--ink-3)" }}>
        Statuts iTop : {Object.values(CHANGE_STATUS).map((s) => s.label).join(", ")}. Un changement refusé ou
        non approuvé n'est pas affiché ; un changement clos ne neutralise plus ses équipements.
      </p>
    </div>
  );
}

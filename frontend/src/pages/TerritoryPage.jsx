import { ChevronRight, MapPin } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import Panel from "../components/ui/Panel";
import Stat, { Meter } from "../components/ui/Stat";
import DataTable from "../components/ui/Table";
import TerritoryMap from "../components/domain/TerritoryMap";
import SlaBreakdown from "../components/domain/SlaBreakdown";
import { complianceColor } from "../lib/itop";
import { NodeStateBadge, SeverityBadge, ToolTag } from "../components/ui/Badge";
import { EmptyState, QueryBoundary, SkeletonRows } from "../components/ui/States";
import { decimal, num, pct, smartTime } from "../lib/format";
import { LEVEL } from "../lib/locality";
import { availabilityColor, toolLabel } from "../lib/vocabulary";
import { useGeoBreakdown, useGeoSite, useSlaIncidents } from "../hooks/queries";
import { useScopeStore } from "../store/scope";

/**
 * Territoire — la désagrégation, du pays jusqu'à l'équipement.
 *
 *   Burkina Faso › Région › Province › Site › Équipement
 *
 * Chaque niveau montre ses indicateurs (disponibilité, pannes, alertes des
 * outils, incidents iTop, SLA) et la liste de ses subdivisions : un clic sur
 * une ligne ou sur la carte descend d'un niveau, le fil d'Ariane remonte.
 * Le niveau courant EST le périmètre de la barre commune : descendre ici
 * filtre aussi tous les autres tableaux de bord, et inversement.
 *
 * Au niveau du site : sa position sur la carte, ses équipements, ses
 * incidents et ses alertes, et le respect des SLA équipement par équipement.
 */
function Breadcrumb({ region, province, site, setPath }) {
  const items = [
    { label: "Burkina Faso", path: {} },
    region && { label: region, path: { region } },
    province && { label: province, path: { region, province } },
    site && { label: site, path: { region, province, site } },
  ].filter(Boolean);
  return (
    <nav className="flex items-center gap-1 flex-wrap text-[13px]" aria-label="Fil d'Ariane">
      {items.map((item, index) => {
        const last = index === items.length - 1;
        return (
          <span key={item.label} className="flex items-center gap-1">
            {index > 0 && <ChevronRight size={13} style={{ color: "var(--ink-3)" }} />}
            {last ? (
              <strong>{item.label}</strong>
            ) : (
              <button
                type="button"
                className="hover:underline"
                style={{ color: "var(--accent-ink)" }}
                onClick={() => setPath(item.path)}
              >
                {item.label}
              </button>
            )}
          </span>
        );
      })}
    </nav>
  );
}

function KpiRow({ totals, level, count }) {
  if (!totals) return null;
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
      <Stat
        label="Disponibilité"
        value={pct(totals.availability_pct, 1)}
        color={availabilityColor(totals.availability_pct)}
        target="≥ 99 %"
        hint={`${num(totals.up)} / ${num(totals.nodes - totals.maintenance)} en service`}
      />
      <Stat label="Équipements" value={num(totals.nodes)} hint={`${num(totals.maintenance)} en maintenance`} />
      <Stat
        label="En panne"
        value={num(totals.down)}
        color={totals.down ? "var(--state-down)" : "var(--state-up)"}
        hint={`${num(totals.degraded)} perturbés · ${num((totals.unknown ?? 0) + (totals.silent ?? 0))} inconnus`}
      />
      <Stat
        label="Alertes outils"
        value={num(totals.alerts)}
        color={totals.alerts_critical ? "var(--sev-critical)" : undefined}
        hint={`${num(totals.alerts_critical)} critiques`}
        to="/alertes"
      />
      <Stat
        label="Incidents iTop"
        value={num(totals.incidents)}
        color={totals.incidents_critical ? "var(--sev-critical)" : undefined}
        hint={`${num(totals.incidents_critical)} critiques · ${num(totals.incidents_unassigned)} non affectés`}
        to="/incidents"
      />
      <Stat
        label={level === "node" ? "Équipements situés" : LEVEL[level].plural}
        value={num(level === "node" ? totals.located_nodes : count)}
        hint={level === "node" ? "avec coordonnées GPS" : "dans ce périmètre"}
      />
    </div>
  );
}

function childColumns(level) {
  const columns = [
    {
      key: "name",
      header: LEVEL[level].label,
      wrap: true,
      render: (row) => (
        <span className="flex items-center gap-1.5">
          <span
            className="font-medium"
            style={{ color: row.unlocated ? "var(--ink-3)" : undefined, fontStyle: row.unlocated ? "italic" : undefined }}
          >
            {row.name}
          </span>
          {!row.unlocated && <ChevronRight size={12} style={{ color: "var(--ink-3)" }} />}
        </span>
      ),
    },
    { key: "nodes", header: "Équip.", width: 58, align: "right", render: (r) => num(r.nodes) },
    {
      key: "availability",
      header: "Disponibilité",
      width: 140,
      render: (r) => (
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <Meter value={r.availability_pct} color={availabilityColor(r.availability_pct)} />
          </div>
          <span className="num text-[11.5px]" style={{ minWidth: 44, color: availabilityColor(r.availability_pct) }}>
            {pct(r.availability_pct, 1)}
          </span>
        </div>
      ),
    },
    {
      key: "down",
      header: "Panne",
      width: 56,
      align: "right",
      render: (r) => <span style={{ color: r.down ? "var(--state-down)" : undefined }}>{num(r.down)}</span>,
    },
    {
      key: "alerts",
      header: "Alertes",
      width: 64,
      align: "right",
      render: (r) => (
        <span title={`${num(r.alerts_critical)} critiques`} style={{ color: r.alerts_critical ? "var(--sev-critical)" : undefined }}>
          {num(r.alerts)}
        </span>
      ),
    },
    {
      key: "incidents",
      header: "Incidents",
      width: 70,
      align: "right",
      render: (r) => (
        <span style={{ color: r.incidents_critical ? "var(--sev-critical)" : undefined }}>{num(r.incidents)}</span>
      ),
    },
  ];
  if (level === "region" || level === "province") {
    columns.splice(2, 0, { key: "sites", header: "Sites", width: 50, align: "right", render: (r) => num(r.sites) });
  }
  return columns;
}

const NODE_COLUMNS = [
  { key: "state", header: "État", width: 100, render: (r) => <NodeStateBadge state={r.state} /> },
  {
    key: "name",
    header: "Équipement",
    wrap: true,
    render: (r) => (
      <span>
        <span className="font-medium">{r.name}</span>
        <span className="block text-[11px] num" style={{ color: "var(--ink-3)" }}>
          {[r.ip, r.node_type].filter(Boolean).join(" · ")}
        </span>
      </span>
    ),
  },
  {
    key: "tools",
    header: "Vu par",
    width: 150,
    wrap: true,
    render: (r) => (
      <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
        {(r.tools ?? []).map(toolLabel).join(", ")}
      </span>
    ),
  },
  {
    key: "alerts",
    header: "Alertes",
    width: 64,
    align: "right",
    render: (r) => <span style={{ color: r.alerts_critical ? "var(--sev-critical)" : undefined }}>{num(r.alerts)}</span>,
  },
  { key: "incidents", header: "Incidents", width: 70, align: "right", render: (r) => num(r.incidents) },
];

function SitePanels({ site }) {
  const detail = useGeoSite(site);
  const data = detail.data;
  return (
    <div className="grid grid-cols-12 gap-2 items-start">
      <Panel title="Fiche du site" className="col-span-12 lg:col-span-4" accent="var(--accent)">
        <QueryBoundary query={detail} compact>
          {() => (
            <div className="text-[12.5px] space-y-1">
              <div className="flex items-center gap-1.5">
                <MapPin size={13} style={{ color: "var(--accent-ink)" }} />
                <span>
                  {data.kpis.latitude != null
                    ? `${decimal(data.kpis.latitude, 5)}, ${decimal(data.kpis.longitude, 5)}`
                    : "coordonnées non renseignées"}
                </span>
              </div>
              {data.kpis.latitude != null && (
                <a
                  className="btn btn-sm"
                  href={`https://www.openstreetmap.org/?mlat=${data.kpis.latitude}&mlon=${data.kpis.longitude}#map=16/${data.kpis.latitude}/${data.kpis.longitude}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Ouvrir dans OpenStreetMap ›
                </a>
              )}
              <div style={{ color: "var(--ink-3)" }}>
                {[data.province, data.region].filter(Boolean).join(" · ")}
              </div>
              {data.organisations.length > 0 && (
                <div>
                  <span style={{ color: "var(--ink-3)" }}>Structures : </span>
                  {data.organisations.join(", ")}
                </div>
              )}
            </div>
          )}
        </QueryBoundary>
      </Panel>
      <Panel title="Incidents iTop du site" className="col-span-12 lg:col-span-4" to="/incidents" toLabel="Tous">
        <QueryBoundary query={detail} compact empty={(d) => !d?.incidents?.length} emptyMessage="Aucun incident iTop ouvert">
          {() => (
            <ul className="space-y-1 max-h-[220px] overflow-auto">
              {data.incidents.map((incident) => (
                <li key={incident.key} className="flex items-start gap-1.5 text-[12px]">
                  <SeverityBadge severity={incident.severity} short />
                  <span className="min-w-0">
                    <Link to={`/incidents?id=${encodeURIComponent(incident.key)}`} className="hover:underline">
                      {incident.ticket_ref ?? incident.ref} — {incident.message}
                    </Link>
                    <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                      {smartTime(incident.since)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryBoundary>
      </Panel>
      <Panel title="Alertes des outils" className="col-span-12 lg:col-span-4" to="/alertes" toLabel="Toutes">
        <QueryBoundary query={detail} compact empty={(d) => !d?.alerts?.length} emptyMessage="Aucune alerte active">
          {() => (
            <ul className="space-y-1 max-h-[220px] overflow-auto">
              {data.alerts.map((alert) => (
                <li key={alert.key} className="flex items-start gap-1.5 text-[12px]">
                  <SeverityBadge severity={alert.severity} short source={alert.source_severity} tool={alert.tool} />
                  <span className="min-w-0">
                    {alert.message}
                    <span className="block text-[11px]" style={{ color: "var(--ink-3)" }}>
                      <ToolTag tool={alert.tool} /> · {alert.node_name} · {smartTime(alert.since)}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </QueryBoundary>
      </Panel>
    </div>
  );
}

export default function TerritoryPage() {
  const navigate = useNavigate();
  const { region, province, site, setPath } = useScopeStore();
  const breakdown = useGeoBreakdown();
  const data = breakdown.data;
  const level = data?.level ?? (site ? "node" : province ? "site" : region ? "province" : "region");
  const slaGroup = level;
  const sla = useSlaIncidents({ groupBy: slaGroup });

  const drill = (row) => {
    if (level === "node") {
      navigate(`/equipements/${encodeURIComponent(row.key)}`);
      return;
    }
    if (row.unlocated) return;
    if (level === "region") setPath({ region: row.name });
    else if (level === "province") setPath({ region, province: row.name });
    else if (level === "site") setPath({ region, province, site: row.name });
  };

  const drillSla = (row) => {
    if (level === "node") return row.key !== "__none__" && navigate(`/equipements/${encodeURIComponent(row.key)}`);
    return drill({ ...row, unlocated: row.name?.endsWith("non renseignée") });
  };

  const title = site ?? province ?? region ?? "Burkina Faso";
  const slaTotals = sla.data?.totals;

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3 flex-wrap">
        <Breadcrumb region={region} province={province} site={site} setPath={setPath} />
        <span className="ml-auto text-[11px]" style={{ color: "var(--ink-3)" }}>
          Respect SLA (30 j) :{" "}
          <strong className="num" style={{ color: complianceColor(slaTotals?.compliance_pct) }}>
            {pct(slaTotals?.compliance_pct, 1)}
          </strong>{" "}
          sur {num(slaTotals?.evaluated)} incident(s) évalué(s)
        </span>
      </div>

      <KpiRow totals={data?.totals} level={level} count={data?.rows?.length} />

      {/* items-start : un panneau court ne s'étire pas à la hauteur de la carte. */}
      <div className="grid grid-cols-12 gap-2 items-start">
        <Panel
          title={level === "region" ? "Carte des régions" : `Carte — ${title}`}
          subtitle={level === "region" ? "couleur = disponibilité · clic pour descendre" : undefined}
          className="col-span-12 xl:col-span-7"
          flush
        >
          <TerritoryMap
            level={level}
            rows={data?.rows}
            region={region}
            onSelect={drill}
            height={level === "node" ? 340 : 400}
          />
        </Panel>

        <Panel
          title={level === "node" ? `Équipements du site` : `${LEVEL[level].plural} — ${title}`}
          subtitle={`${num(data?.rows?.length)} élément(s), les plus en souffrance d'abord`}
          className="col-span-12 xl:col-span-5"
          flush
        >
          <div style={{ maxHeight: level === "node" ? 340 : 400, overflow: "auto" }}>
            <QueryBoundary
              query={breakdown}
              skeleton={<SkeletonRows rows={8} columns={6} />}
              empty={(d) => !d?.rows?.length}
              emptyMessage="Aucun équipement dans ce périmètre"
              emptyHint="Vérifiez la recherche saisie dans la barre de périmètre."
            >
              {(d) => (
                <DataTable
                  dense
                  columns={level === "node" ? NODE_COLUMNS : childColumns(level)}
                  rows={d.rows}
                  rowKey={(row) => row.key}
                  onRowClick={drill}
                />
              )}
            </QueryBoundary>
          </div>
        </Panel>
      </div>

      {site && <SitePanels site={site} />}

      {/* Sans incident sur la période, le panneau n'est pas affiché : le taux
          (« — sur 0 incident ») est déjà rappelé en tête de page. */}
      {(sla.isLoading || sla.isError || (sla.data?.rows?.length ?? 0) > 0) && (
      <Panel
        title={`Respect des SLA des incidents iTop — par ${LEVEL[slaGroup].label.toLowerCase()}`}
        subtitle="30 derniers jours · délais de résolution comparés aux objectifs par gravité"
        to="/sla"
        toLabel="Écran SLA"
        flush
      >
        {sla.isError ? (
          <EmptyState
            compact
            message="SLA indisponibles"
            hint={sla.error?.response?.data?.detail?.detail ?? "iTop n'a pas répondu."}
          />
        ) : (
          <SlaBreakdown query={sla} groupBy={slaGroup} onSelect={drillSla} maxHeight={300} />
        )}
      </Panel>
      )}
    </div>
  );
}

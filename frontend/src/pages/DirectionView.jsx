import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Gauge,
  Radio,
  ServerCrash,
  ShieldCheck,
} from "lucide-react";

import { DashboardSummary } from "../components/domain/FleetInsights";
import {
  CauseList,
  IncidentScorecard,
  OrganisationTable,
  RecurrentTable,
  TopSitesTable,
} from "../components/domain/IncidentInsights";
import Panel from "../components/ui/Panel";
import { Meter } from "../components/ui/Stat";
import TerritoryMap from "../components/domain/TerritoryMap";
import { complianceColor } from "../lib/itop";
import { LineChart } from "../components/charts";
import { Notice } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { NodeStateBadge, SeverityBadge } from "../components/ui/Badge";
import { decimal, delta, duration, monthLabel, num, pct } from "../lib/format";
import { LEVEL, localityKey } from "../lib/locality";
import { availabilityColor } from "../lib/vocabulary";
import { errorMessage } from "../api/client";
import { report } from "../api/noc";
import { saveBlob } from "../lib/download";
import { usePeriodStore } from "../store/ui";
import { scopeLabel, useScopeStore } from "../store/scope";
import { usePermission } from "../hooks/useSession";
import { PERMISSIONS } from "../lib/permissions";
import {
  useGeoBreakdown,
  useIncidentKpis,
  useItopIncidents,
  useKpiSummary,
  useKpiTrend,
  useOrganisations,
  useOverview,
  useSlaIncidents,
} from "../hooks/queries";

/**
 * Vue de direction — réservée aux directeurs.
 *
 * Organisée pour être LUE EN UNE MINUTE, de haut en bas :
 *
 *   1. Quatre réponses : le réseau marche-t-il ? combien d'incidents ?
 *      tenons-nous nos engagements ? qu'est-ce qui est en panne ?
 *      Chaque carte dit son verdict en mots, pas seulement en chiffres.
 *   2. Où : la carte et le classement des régions, cliquables jusqu'au
 *      site puis à l'équipement.
 *   3. Ce qui demande une décision : des points d'attention rédigés.
 *   4. L'évolution et le détail des engagements.
 *   5. La grille « KPI incidents » du document de l'agence (cible, réel,
 *      statut), puis qui souffre : organisations, sites, équipements
 *      récurrents, causes.
 *
 * Tout suit le périmètre de la barre commune : choisir une région montre
 * ses provinces, une province ses sites, un site ses équipements.
 *
 * Un panneau sans donnée n'est PAS affiché — pas de cadre vide à l'écran —
 * et aucun geste d'exploitation n'est proposé ici.
 */

function Headline({ icon: Icon, label, value, color, verdict, detail, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="panel text-left px-3 py-2.5 gap-3 items-start hover:border-[var(--border-strong)] transition-colors"
      // `.panel` est une colonne : l'icône doit rester à gauche du texte.
      style={{ borderLeft: `3px solid ${color}`, flexDirection: "row" }}
    >
      <Icon size={22} style={{ color, flexShrink: 0, marginTop: 2 }} aria-hidden="true" />
      <span className="min-w-0">
        <span
          className="block text-[10.5px] font-semibold uppercase tracking-[0.07em]"
          style={{ color: "var(--ink-3)" }}
        >
          {label}
        </span>
        <span className="block num font-semibold leading-tight" style={{ fontSize: 28, color }}>
          {value}
        </span>
        <span className="block text-[12px] font-medium" style={{ color }}>
          {verdict}
        </span>
        {detail && (
          <span className="block text-[11px] mt-0.5" style={{ color: "var(--ink-3)" }}>
            {detail}
          </span>
        )}
      </span>
    </button>
  );
}

function availabilityVerdict(value) {
  if (value == null) return "non mesurée";
  if (value >= 99) return "objectif atteint (≥ 99 %)";
  if (value >= 95) return "sous l'objectif de 99 %";
  return "situation perturbée";
}

/** Points d'attention rédigés à partir des données, du plus grave au moins grave. */
function buildInsights({ overview, breakdown, sla, level, kpis, openIncidents }) {
  const insights = [];
  const rows = (breakdown?.rows ?? []).filter((row) => !row.unlocated);
  const levelLabel = LEVEL[level]?.label ?? "Zone";

  if (overview?.incidents_critical) {
    insights.push({
      tone: "critical",
      text: `${num(overview.incidents_critical)} incident(s) iTop critique(s) ouvert(s).`,
      to: "/incidents?severity=critical",
    });
  }
  if (openIncidents?.critical_unassigned) {
    insights.push({
      tone: "critical",
      text: `${num(openIncidents.critical_unassigned)} incident(s) critique(s) sans agent : personne ne les traite.`,
      to: "/incidents?severity=critical",
    });
  }
  if (overview?.incidents_unassigned) {
    insights.push({
      tone: "warning",
      text: `${num(overview.incidents_unassigned)} incident(s) iTop sans agent affecté.`,
      to: "/incidents",
    });
  }
  if (sla?.totals?.breached) {
    insights.push({
      tone: "critical",
      text: `${num(sla.totals.breached)} engagement(s) de délai non tenu(s) sur 30 jours (respect ${pct(
        sla.totals.compliance_pct,
        1,
      )}).`,
      to: "/sla",
    });
  }
  if (kpis?.recurrent_nodes) {
    insights.push({
      tone: "warning",
      text: `${num(kpis.recurrent_nodes)} équipement(s) récurrent(s) : ${num(
        kpis.recurrent_incidents,
      )} tickets sur 30 jours (au moins ${kpis.recurrent_threshold} chacun).`,
    });
  }
  if (kpis?.without_cause_pct != null && kpis.without_cause_pct > 5) {
    insights.push({
      tone: "warning",
      text: `${pct(kpis.without_cause_pct, 0)} des incidents résolus sans cause identifiée dans iTop (cible ≤ 5 %).`,
    });
  }
  if (level !== "node") {
    const worst = rows
      .filter((row) => row.availability_pct != null && row.availability_pct < 95)
      .sort((a, b) => a.availability_pct - b.availability_pct)
      .slice(0, 3);
    for (const row of worst) {
      insights.push({
        tone: row.availability_pct < 90 ? "critical" : "warning",
        text: `${levelLabel} ${row.name} : disponibilité ${pct(row.availability_pct, 1)}, ${num(
          row.down,
        )} équipement(s) en panne sur ${num(row.nodes)}.`,
        row,
      });
    }
  }
  for (const row of (sla?.rows ?? [])
    .filter((item) => item.compliance_pct != null && item.compliance_pct < 85 && item.evaluated >= 3)
    .slice(0, 2)) {
    insights.push({
      tone: "warning",
      text: `SLA — ${row.name} : ${pct(row.compliance_pct, 1)} de respect (${num(row.breached)} dépassement(s)).`,
      to: "/sla",
    });
  }
  const unlocated = (breakdown?.rows ?? []).find((row) => row.unlocated);
  if (unlocated && breakdown?.totals?.nodes && unlocated.nodes / breakdown.totals.nodes > 0.1) {
    insights.push({
      tone: "info",
      text: `${num(unlocated.nodes)} équipement(s) (${pct(
        (100 * unlocated.nodes) / breakdown.totals.nodes,
        0,
      )}) sans ${levelLabel.toLowerCase()} renseignée dans les outils : comptés, mais non localisés.`,
    });
  }
  return insights;
}

const TONE = {
  critical: { color: "var(--sev-critical)", icon: AlertTriangle },
  warning: { color: "var(--sev-medium)", icon: AlertTriangle },
  info: { color: "var(--accent-ink)", icon: Gauge },
};

function RankingTable({ rows, level, slaByName, onSelect }) {
  // Colonne SLA masquée tant qu'aucune ligne n'a de taux : une colonne
  // entière de « — » n'apprend rien et prend la place des autres.
  const showSla = rows.some(
    (row) => slaByName.get(level === "node" ? row.key : localityKey(row.name))?.compliance_pct != null,
  );
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>{LEVEL[level]?.label}</th>
          <th style={{ width: 150 }}>{level === "node" ? "État" : "Disponibilité"}</th>
          {level !== "node" && <th style={{ width: 56, textAlign: "right" }}>Panne</th>}
          <th style={{ width: 68, textAlign: "right" }}>Incidents</th>
          {showSla && <th style={{ width: 64, textAlign: "right" }}>SLA</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const slaRow = slaByName.get(level === "node" ? row.key : localityKey(row.name));
          return (
            <tr key={row.key} className={row.unlocated ? "" : "row-clickable"} onClick={() => onSelect(row)}>
              <td>
                <span
                  className="font-medium"
                  style={{
                    color: row.unlocated ? "var(--ink-3)" : undefined,
                    fontStyle: row.unlocated ? "italic" : undefined,
                  }}
                >
                  {row.name}
                </span>
                {level !== "node" && (
                  <span className="block text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                    {num(row.nodes)} équipements{row.sites != null ? ` · ${num(row.sites)} sites` : ""}
                  </span>
                )}
              </td>
              <td>
                {level === "node" ? (
                  <NodeStateBadge state={row.state} />
                ) : (
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <Meter value={row.availability_pct} color={availabilityColor(row.availability_pct)} />
                    </div>
                    <span className="num text-[11.5px]" style={{ minWidth: 44, color: availabilityColor(row.availability_pct) }}>
                      {pct(row.availability_pct, 1)}
                    </span>
                  </div>
                )}
              </td>
              {level !== "node" && (
                <td className="num" style={{ textAlign: "right", color: row.down ? "var(--state-down)" : undefined }}>
                  {num(row.down)}
                </td>
              )}
              <td className="num" style={{ textAlign: "right", color: row.incidents_critical ? "var(--sev-critical)" : undefined }}>
                {num(row.incidents)}
              </td>
              {showSla && (
                <td className="num" style={{ textAlign: "right", color: complianceColor(slaRow?.compliance_pct) }}>
                  {pct(slaRow?.compliance_pct, 0)}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function DirectionView() {
  const navigate = useNavigate();
  const { month, year } = usePeriodStore();
  const scope = useScopeStore();
  const canDownload = usePermission(PERMISSIONS.DOWNLOAD_REPORT);
  const national = !scope.region && !scope.province && !scope.site && !scope.search;

  const overview = useOverview();
  const breakdown = useGeoBreakdown();
  const level = breakdown.data?.level ?? "region";
  const sla = useSlaIncidents({ groupBy: level });
  const summary = useKpiSummary();
  const trend = useKpiTrend(180);
  const kpis = useIncidentKpis();
  // Compteurs seuls : la liste n'est pas affichée ici.
  const openIncidents = useItopIncidents({ limit: 1 });
  const organisations = useOrganisations();

  const [downloadError, setDownloadError] = useState(null);
  const [downloading, setDownloading] = useState(null);

  const o = overview.data;
  const slaTotals = sla.data?.totals;
  const availability = o?.fleet_availability_pct;
  const down = o?.nodes_by_state ? o.nodes_by_state.down ?? 0 : null;

  const slaByName = useMemo(() => {
    const index = new Map();
    for (const row of sla.data?.rows ?? []) {
      index.set(level === "node" ? row.key : localityKey(row.name), row);
    }
    return index;
  }, [sla.data, level]);

  const insights = buildInsights({
    overview: o,
    breakdown: breakdown.data,
    sla: sla.data,
    level,
    kpis: kpis.data,
    openIncidents: openIncidents.data,
  });
  const trendData = (trend.data ?? []).filter((point) => point.availability_pct != null);
  const causeItems = (kpis.data?.causes ?? []).slice(0, 6);
  const monthDelta = summary.data?.vs_previous_month?.availability_delta;
  const orgRows = (organisations.data ?? []).slice(0, 12);
  const recurrentRows = kpis.data?.recurrent ?? [];
  const topSites = kpis.data?.top_sites ?? [];
  const severityRows = sla.data?.by_severity ?? [];
  const showTrend = national && trendData.length > 1;

  const drill = (row) => {
    if (!row || row.unlocated) return;
    if (level === "node") navigate(`/equipements/${encodeURIComponent(row.key)}`);
    else if (level === "region") scope.setPath({ region: row.name });
    else if (level === "province") scope.setPath({ region: scope.region, province: row.name });
    else scope.setPath({ region: scope.region, province: scope.province, site: row.name });
  };

  const download = async (format) => {
    setDownloadError(null);
    setDownloading(format);
    try {
      const blob = await report.monthly({ month, year, format });
      await saveBlob(blob, `rapport-noc-${year}-${String(month).padStart(2, "0")}.${format}`);
    } catch (error) {
      setDownloadError(error.message || errorMessage(error));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="space-y-2">
      <PageHeader
        title="Pilotage du réseau"
        subtitle={`${scopeLabel(scope)} · état à l'instant, engagements sur 30 jours`}
        actions={
          canDownload && (
            <div className="flex items-center gap-1">
              <span className="text-[11px] mr-1" style={{ color: "var(--ink-3)" }}>
                Rapport {monthLabel(month, year)}
              </span>
              <button type="button" className="btn btn-sm" disabled={downloading !== null} onClick={() => download("pdf")}>
                <Download size={13} /> {downloading === "pdf" ? "…" : "PDF"}
              </button>
              <button type="button" className="btn btn-sm" disabled={downloading !== null} onClick={() => download("docx")}>
                {downloading === "docx" ? "…" : "Word"}
              </button>
            </div>
          )
        }
      />

      <DashboardSummary />

      {downloadError && (
        <Notice tone="error" onClose={() => setDownloadError(null)}>
          {downloadError}
        </Notice>
      )}

      {/* 1. Les quatre réponses */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
        <Headline
          icon={Gauge}
          label="Disponibilité du réseau"
          value={pct(availability, 1)}
          color={availabilityColor(availability)}
          verdict={availabilityVerdict(availability)}
          detail={
            o &&
            `${num(o.nodes_by_state?.up ?? 0)} en service sur ${num(
              o.nodes_total - (o.nodes_by_state?.maintenance ?? 0),
            )}${
              national && summary.data?.kpi?.network_availability_pct != null
                ? ` · moyenne du mois ${pct(summary.data.kpi.network_availability_pct, 1)}${
                    monthDelta != null
                      ? ` (${delta(monthDelta, (v) => `${decimal(v, 1)} pt`)} vs mois préc.)`
                      : ""
                  }`
                : ""
            }`
          }
          onClick={() => navigate("/territoire")}
        />
        <Headline
          icon={Radio}
          label="Incidents iTop ouverts"
          value={num(o?.incidents_total)}
          color={
            o?.incidents_critical
              ? "var(--sev-critical)"
              : o?.incidents_total
                ? "var(--sev-high)"
                : "var(--state-up)"
          }
          verdict={
            o?.incidents_total == null
              ? "—"
              : o.incidents_critical
                ? `${num(o.incidents_critical)} critique(s)`
                : o.incidents_total
                  ? "aucun critique"
                  : "aucun incident en cours"
          }
          detail={o && `${num(o.incidents_unassigned)} non affecté(s) · ${num(o.incidents_high)} haute priorité`}
          onClick={() => navigate("/incidents")}
        />
        <Headline
          icon={ShieldCheck}
          label="Respect des SLA (30 j)"
          value={pct(slaTotals?.compliance_pct, 1)}
          color={complianceColor(slaTotals?.compliance_pct)}
          verdict={
            sla.isError
              ? "historique iTop indisponible"
              : slaTotals?.compliance_pct == null
                ? "aucun incident évalué"
                : slaTotals.compliance_pct >= 95
                  ? "objectif atteint (≥ 95 %)"
                  : `${num(slaTotals.breached)} engagement(s) non tenu(s)`
          }
          detail={
            slaTotals &&
            `${num(slaTotals.evaluated)} incident(s) évalué(s) · résolution moy. ${duration(slaTotals.mttr_minutes)}`
          }
          onClick={() => navigate("/sla")}
        />
        <Headline
          icon={down ? ServerCrash : CheckCircle2}
          label="Équipements en panne"
          value={num(down)}
          color={down ? "var(--state-down)" : "var(--state-up)"}
          verdict={
            down == null ? "—" : down ? `sur ${num(o?.sites_impacted)} site(s) touché(s)` : "aucune panne en cours"
          }
          detail={
            o &&
            `${num(o.alerts_by_severity?.critical ?? 0)} alerte(s) critique(s) des outils · ${num(
              o.nodes_by_state?.maintenance ?? 0,
            )} en maintenance`
          }
          onClick={() => navigate("/equipements?state=down")}
        />
      </div>

      {/* 2. Où — carte et classement */}
      <div className="grid grid-cols-12 gap-2 items-start">
        <Panel
          title={level === "region" ? "Disponibilité par région" : `Carte — ${scopeLabel(scope)}`}
          subtitle="clic pour descendre"
          className="col-span-12 xl:col-span-6"
          flush
        >
          <TerritoryMap level={level} rows={breakdown.data?.rows} region={scope.region} onSelect={drill} height={360} />
        </Panel>

        <Panel
          title={`Classement — ${LEVEL[level]?.plural ?? ""}`}
          subtitle="les plus en difficulté d'abord"
          className="col-span-12 xl:col-span-6"
          to="/territoire"
          toLabel="Explorer"
          flush
        >
          <div style={{ maxHeight: 360, overflow: "auto" }}>
            <QueryBoundary
              query={breakdown}
              skeleton={<SkeletonRows rows={8} columns={5} />}
              empty={(d) => !d?.rows?.length}
              emptyMessage="Aucun équipement dans ce périmètre"
            >
              {(d) => <RankingTable rows={d.rows} level={level} slaByName={slaByName} onSelect={drill} />}
            </QueryBoundary>
          </div>
        </Panel>
      </div>

      {/* 3. Décisions — 4. évolution */}
      <div className="grid grid-cols-12 gap-2 items-start">
        <Panel
          title="Points d'attention"
          accent={insights.some((item) => item.tone === "critical") ? "var(--sev-critical)" : "var(--state-up)"}
          className={`col-span-12 ${showTrend ? "xl:col-span-5" : ""}`}
        >
          {overview.isLoading || breakdown.isLoading ? (
            <SkeletonRows rows={3} columns={1} />
          ) : overview.isError || breakdown.isError ? (
            // Sans données, « aucun point d'attention » se lirait « tout va bien ».
            <p className="text-[12.5px]" style={{ color: "var(--sev-medium)" }}>
              Points d'attention indisponibles : l'état du réseau n'a pas pu être lu.
            </p>
          ) : insights.length === 0 ? (
            <p className="text-[12.5px] flex items-center gap-2" style={{ color: "var(--state-up)" }}>
              <CheckCircle2 size={15} /> Aucun point d'attention : disponibilité, incidents et engagements sont
              dans les objectifs.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {insights.map((item, index) => {
                const tone = TONE[item.tone];
                const Icon = tone.icon;
                const clickable = Boolean(item.to || item.row);
                return (
                  <li key={index}>
                    <button
                      type="button"
                      disabled={!clickable}
                      onClick={() => (item.row ? drill(item.row) : navigate(item.to))}
                      className="w-full text-left flex items-start gap-2 text-[12.5px]"
                      style={{ cursor: clickable ? "pointer" : "default" }}
                    >
                      <Icon size={14} style={{ color: tone.color, flexShrink: 0, marginTop: 2 }} />
                      <span className={clickable ? "hover:underline" : ""}>{item.text}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        {showTrend && (
          <Panel
            title="Évolution sur 6 mois"
            subtitle="disponibilité moyenne quotidienne du réseau"
            className="col-span-12 xl:col-span-7"
          >
            <LineChart
              height={170}
              labels={trendData.map((point) => point.label)}
              targetLine={99}
              valueFormatter={(value) => `${decimal(value, 1)} %`}
              series={[
                {
                  label: "Disponibilité",
                  data: trendData.map((point) => point.availability_pct),
                  color: "var(--accent)",
                  fill: true,
                },
              ]}
            />
          </Panel>
        )}
      </div>

      {(severityRows.length > 0 || causeItems.length > 0) && (
        <div className="grid grid-cols-12 gap-2">
          {severityRows.length > 0 && (
            <Panel
              title="Engagements par gravité (30 j)"
              to="/sla"
              toLabel="Détail SLA"
              className={`col-span-12 ${causeItems.length ? "xl:col-span-7" : ""}`}
              flush
            >
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: 100 }}>Gravité</th>
                    <th style={{ textAlign: "right" }}>Incidents</th>
                    <th style={{ textAlign: "right" }}>Résolution moy.</th>
                    <th style={{ textAlign: "right" }}>Objectif</th>
                    <th style={{ width: 170 }}>Respect</th>
                  </tr>
                </thead>
                <tbody>
                  {severityRows.map((row) => (
                    <tr key={row.severity}>
                      <td>
                        <SeverityBadge severity={row.severity} />
                      </td>
                      <td className="num" style={{ textAlign: "right" }}>{num(row.incidents)}</td>
                      <td className="num" style={{ textAlign: "right" }}>{duration(row.mttr_minutes)}</td>
                      <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                        {duration(sla.data.targets?.[row.severity]?.ttr)}
                      </td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="flex-1">
                            <Meter value={row.compliance_pct} color={complianceColor(row.compliance_pct)} />
                          </div>
                          <span className="num text-[11.5px]" style={{ minWidth: 44, color: complianceColor(row.compliance_pct) }}>
                            {pct(row.compliance_pct, 0)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          )}
          {causeItems.length > 0 && (
            <Panel
              title="Principales causes"
              subtitle={`code de résolution iTop, 30 j${
                kpis.data?.without_cause_pct != null
                  ? ` · ${pct(kpis.data.without_cause_pct, 0)} sans cause`
                  : ""
              }`}
              className={`col-span-12 ${severityRows.length ? "xl:col-span-5" : ""}`}
            >
              <CauseList causes={causeItems} />
            </Panel>
          )}
        </div>
      )}

      {/* 5. Grille de l'agence et organisations */}
      <div className="grid grid-cols-12 gap-2 items-start">
        <Panel
          title="KPI incidents"
          subtitle="grille de l'agence · tickets iTop, 30 j et file en cours"
          className={`col-span-12 ${orgRows.length ? "xl:col-span-6" : ""}`}
          to="/incidents"
          toLabel="Incidents"
          flush
        >
          <QueryBoundary
            query={kpis}
            skeleton={<SkeletonRows rows={8} columns={4} />}
          >
            {(data) => <IncidentScorecard kpis={data} open={openIncidents.data} sla={slaTotals} />}
          </QueryBoundary>
        </Panel>
        {orgRows.length > 0 && (
          <Panel
            title="Disponibilité par organisation"
            subtitle="ministères et structures (CI iTop) · incidents et SLA sur 30 j"
            className="col-span-12 xl:col-span-6"
            flush
          >
            <div style={{ maxHeight: 420, overflow: "auto" }}>
              <OrganisationTable organisations={orgRows} incidents={kpis.data?.by_organisation} />
            </div>
          </Panel>
        )}
      </div>

      {(topSites.length > 0 || recurrentRows.length > 0) && (
        <div className="grid grid-cols-12 gap-2 items-start">
          {topSites.length > 0 && (
            <Panel
              title="Top 10 des sites les plus incidentés"
              subtitle="tickets iTop ouverts sur 30 j"
              className={`col-span-12 ${recurrentRows.length ? "xl:col-span-6" : ""}`}
              to="/territoire"
              toLabel="Territoire"
              flush
            >
              <TopSitesTable rows={topSites} />
            </Panel>
          )}
          {recurrentRows.length > 0 && (
            <Panel
              title="Équipements récurrents"
              subtitle={`au moins ${kpis.data.recurrent_threshold} tickets sur 30 j`}
              accent="var(--sev-medium)"
              className={`col-span-12 ${topSites.length ? "xl:col-span-6" : ""}`}
              flush
            >
              <RecurrentTable rows={recurrentRows} />
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}

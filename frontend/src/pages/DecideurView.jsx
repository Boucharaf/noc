import React from "react";
import { Activity, AlertOctagon, Clock, ShieldCheck, FileDown } from "lucide-react";
import KPICard from "../components/KPICard";
import Card from "../components/Card";
import SLATracker from "../components/SLATracker";
import BurkinaFasoMap from "../components/map/BurkinaFasoMap";
import LocalityBulletList from "../components/map/LocalityBulletList";
import TrendLine from "../components/charts/TrendLine";
import { useKpiSummary, useKpiLocalities, useKpiTrend, useSLA, useKpiLocalitiesMap } from "../hooks/useKPI";
import { useCoverage } from "../hooks/useOperational";
import { useIncidentsCount } from "../hooks/useRealtime";
import { useHasPermission } from "../hooks/usePermission";
import { usePeriodStore } from "../store";
import { PERMISSIONS } from "../api/permissions";
import { downloadMonthlyReport } from "../api/report";
import { monthBounds } from "../utils/format";
import { STATUS } from "../theme/colors";

/**
 * Niveau 1 du document métier : "Disponibilité globale | Incidents critiques |
 * SLA | MTTR | Top 10 sites | Tendance 1 mois". Rien d'opérationnel ici (pas
 * de file d'incidents à traiter, pas de bouton d'acquittement) — c'est un
 * écran de décision, pas un poste de travail.
 */
const DecideurView = () => {
  const { month, year } = usePeriodStore();
  const { data: summary, isLoading: loadingSummary } = useKpiSummary();
  const { data: localities = [] } = useKpiLocalities(10);
  const { data: mapLocalities = [] } = useKpiLocalitiesMap();
  const { data: trend = [] } = useKpiTrend(6);
  const { data: sla } = useSLA();
  const { data: coverage } = useCoverage();
  const canDownload = useHasPermission(PERMISSIONS.DOWNLOAD_REPORT);

  const { dateFrom, dateTo } = monthBounds(month, year);
  const { data: criticalCount, isLoading: loadingCritical } = useIncidentsCount({
    severity: "critical", dateFrom, dateTo,
  });

  const kpi = summary?.kpi;
  const delta = summary?.vs_previous_month;

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold">Vue Décideur</h1>
          <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
            {summary?.period.label ?? "—"} · RESINA National
          </p>
        </div>
        {canDownload && (
          <button
            onClick={() => downloadMonthlyReport(month, year, "pdf")}
            className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            <FileDown className="h-3.5 w-3.5" /> Rapport mensuel
          </button>
        )}
      </div>

      {/* Disponibilité globale | Incidents critiques | SLA | MTTR */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KPICard
          size="hero"
          title="Disponibilité globale du RESINA"
          value={kpi?.network_availability_pct ?? "—"}
          unit="%"
          icon={Activity}
          loading={loadingSummary}
          sentiment={kpi && kpi.network_availability_pct < 99 ? "bad" : "good"}
          trend={delta ? `${delta.availability_delta > 0 ? "+" : ""}${delta.availability_delta}%` : null}
          trendDirection={delta?.availability_delta > 0 ? "up" : delta?.availability_delta < 0 ? "down" : undefined}
          accent={STATUS.good}
        />
        <KPICard
          size="hero"
          title="Incidents critiques (mois)"
          value={criticalCount ?? "—"}
          icon={AlertOctagon}
          loading={loadingCritical}
          sentiment={criticalCount > 5 ? "bad" : "good"}
          accent={STATUS.critical}
        />
        <KPICard
          title="MTTR moyen"
          value={kpi ? Math.round(kpi.avg_mttr_minutes) : "—"}
          unit="min"
          icon={Clock}
          loading={loadingSummary}
          sentiment={kpi && kpi.avg_mttr_minutes > 240 ? "bad" : "good"}
          accent={STATUS.warning}
        />
        <KPICard
          title="Sites en état critique"
          value={kpi?.critical_localities ?? "—"}
          icon={ShieldCheck}
          loading={loadingSummary}
          sentiment={kpi?.critical_localities > 0 ? "bad" : "good"}
          accent={STATUS.serious}
        />
      </div>

      {/* SLA */}
      <div>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--color-text-secondary)" }}>
          Respect des SLA
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {(sla?.indicators ?? []).map((ind) => (
            <SLATracker key={ind.metric} metric={ind.metric} value={ind.value} target={ind.target} />
          ))}
          {!sla && (
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>Chargement des indicateurs SLA…</p>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
        {/* Tendance 1 mois (évolution vs. mois précédent + historique 6 mois de contexte) */}
        <Card
          title="Tendance"
          subtitle={delta ? `${delta.incidents_delta > 0 ? "+" : ""}${delta.incidents_delta} incidents vs mois précédent` : undefined}
          className="lg:col-span-3"
          bodyClassName="h-64"
        >
          <TrendLine points={trend} />
        </Card>

        {/* Top 10 sites */}
        <Card title="Top 10 sites les plus incidentés" className="lg:col-span-2" bodyClassName="p-2">
          <ul className="divide-y" style={{ borderColor: "var(--color-border)" }}>
            {localities.slice(0, 10).map((l, i) => (
              <li key={l.locality_id} className="flex items-center gap-3 px-2 py-2 text-sm">
                <span className="w-5 shrink-0 text-center font-mono text-xs" style={{ color: "var(--color-text-muted)" }}>{i + 1}</span>
                <span className="min-w-0 flex-1 truncate" title={l.locality}>{l.locality}</span>
                <span className="shrink-0 font-mono text-xs font-semibold" style={{ color: STATUS.critical }}>{l.total_incidents}</span>
              </li>
            ))}
            {localities.length === 0 && (
              <li className="px-2 py-4 text-center text-sm" style={{ color: "var(--color-text-muted)" }}>Aucune donnée.</li>
            )}
          </ul>
        </Card>
      </div>

      {/* Disponibilité par site (couvre "disponibilité par site" du doc — le regroupement
          par ministère/structure n'existe pas dans le modèle de données actuel, voir note ci-dessous) */}
      <Card
        title="Disponibilité par site"
        subtitle="Le regroupement par ministère/structure n'existe pas encore dans le modèle de données (dim_locality n'a pas de champ organisation)"
        bodyClassName="p-3"
      >
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2" style={{ height: 340 }}>
            <BurkinaFasoMap localities={mapLocalities} />
          </div>
          <div>
            <LocalityBulletList localities={mapLocalities} maxHeight="340px" />
          </div>
        </div>
        {coverage && (
          <div className="mt-3 flex flex-wrap items-center gap-4 border-t pt-3 text-xs" style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}>
            <span>Couverture de supervision : <strong style={{ color: "var(--color-text-primary)" }}>{coverage.coverage_pct}%</strong></span>
            <span>{coverage.monitored_assets}/{coverage.total_assets} équipements supervisés</span>
          </div>
        )}
      </Card>
    </div>
  );
};

export default DecideurView;

import React from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock, Signal } from "lucide-react";
import KPICard from "../components/KPICard";
import Card from "../components/Card";
import WeeklyBar from "../components/charts/WeeklyBar";
import MTTRDonut from "../components/charts/MTTRDonut";
import PeriodComparison from "../components/PeriodComparison";
import BurkinaFasoMap from "../components/map/BurkinaFasoMap";
import LocalityBulletList from "../components/map/LocalityBulletList";
import {
  useKpiSummary,
  useKpiTrend,
  useKpiCauses,
  useKpiLocalitiesMap,
} from "../hooks/useKPI";

const ChartLoading = () => (
  <div
    className="flex h-full min-h-32 items-center justify-center text-sm"
    style={{ color: "var(--color-text-muted)" }}
  >
    Chargement…
  </div>
);

const GlobalView = () => {
  const navigate = useNavigate();
  const { data: summary, isLoading: summaryLoading } = useKpiSummary();
  const { data: trend, isLoading: trendLoading } = useKpiTrend(6);
  const { data: causes, isLoading: causesLoading } = useKpiCauses();
  const { data: localities = [], isLoading: mapLoading } =
    useKpiLocalitiesMap();

  const kpi = summary?.kpi;
  const delta = summary?.vs_previous_month;

  const goToLocality = (localityId) =>
    navigate("/locality", { state: { localityId } });

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="shrink-0">
        <h2
          className="text-xl font-bold"
          style={{ color: "var(--color-text-primary)" }}
        >
          Vue Globale
        </h2>
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          Supervision H24 du réseau national —{" "}
          {kpi ? `${kpi.total_incidents} incidents` : "…"} ce mois-ci
        </p>
      </div>

      <div className="grid shrink-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title="Total Incidents"
          value={kpi?.total_incidents}
          icon={AlertTriangle}
          trend={
            delta
              ? `${delta.incidents_delta >= 0 ? "+" : ""}${delta.incidents_delta}`
              : null
          }
          trendDirection={
            delta ? (delta.incidents_delta >= 0 ? "up" : "down") : null
          }
          sentiment={
            delta ? (delta.incidents_delta <= 0 ? "good" : "bad") : "neutral"
          }
          loading={summaryLoading}
        />
        <KPICard
          title="Disponibilité Réseau"
          value={kpi ? `${kpi.network_availability_pct}%` : null}
          icon={Signal}
          trend={
            delta
              ? `${delta.availability_delta >= 0 ? "+" : ""}${delta.availability_delta}%`
              : null
          }
          trendDirection={
            delta ? (delta.availability_delta >= 0 ? "up" : "down") : null
          }
          sentiment={
            delta ? (delta.availability_delta >= 0 ? "good" : "bad") : "neutral"
          }
          loading={summaryLoading}
        />
        <KPICard
          title="Taux de Résolution"
          value={kpi ? `${kpi.resolution_rate_pct}%` : null}
          icon={CheckCircle2}
          loading={summaryLoading}
        />
        <KPICard
          title="MTTR Moyen"
          value={kpi ? `${kpi.avg_mttr_minutes} min` : null}
          icon={Clock}
          loading={summaryLoading}
        />
      </div>

      {/* Below the KPI row, content shares whatever space remains on tall
          screens (no page scroll — the main content area exactly fits). If a
          screen is too short, `main` scrolls as the fallback and the map/list
          row keeps a usable floor instead of collapsing to nothing. */}
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <div className="grid min-h-[260px] flex-1 auto-rows-fr grid-cols-1 gap-4 lg:grid-cols-5">
          <Card
            title="Carte de Supervision"
            subtitle="Cliquez une localité pour la retrouver dans Vue par Localité"
            className="flex h-full flex-col lg:col-span-3"
            bodyClassName="flex min-h-0 flex-1 flex-col"
          >
            {mapLoading ? (
              <ChartLoading />
            ) : (
              <BurkinaFasoMap
                localities={localities}
                onSelect={goToLocality}
                height="100%"
              />
            )}
          </Card>
          <Card
            title="Localités"
            subtitle="Triées par volume d'incidents"
            className="flex h-full flex-col lg:col-span-2"
            bodyClassName="flex min-h-0 flex-1 flex-col"
          >
            {mapLoading ? (
              <ChartLoading />
            ) : (
              <LocalityBulletList
                localities={localities}
                onSelect={goToLocality}
                maxHeight="100%"
              />
            )}
          </Card>
        </div>

        <div className="grid shrink-0 grid-cols-1 gap-4 lg:grid-cols-2">
          <Card title="Évolution Mensuelle" subtitle="6 derniers mois">
            <div className="h-20">
              {trendLoading ? <ChartLoading /> : <WeeklyBar points={trend} />}
            </div>
          </Card>
          <Card title="Répartition des incidents par cause">
            <div className="h-20">
              {causesLoading ? <ChartLoading /> : <MTTRDonut causes={causes} />}
            </div>
          </Card>
        </div>

        <div className="shrink-0">
          <PeriodComparison />
        </div>
      </div>
    </div>
  );
};

export default GlobalView;

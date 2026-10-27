import { useState } from "react";
import { Download, FileText } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { BarChart } from "../components/charts";
import { Notice } from "../components/ui/Controls";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { MONTHS_FR_SHORT, decimal, duration, monthLabel, num, pct } from "../lib/format";
import { errorMessage } from "../api/client";
import { report } from "../api/noc";
import { saveBlob } from "../lib/download";
import { useKpiSummary, useKpiTrend, useSla } from "../hooks/queries";
import { usePeriodStore } from "../store/ui";

/**
 * Rapports d'exploitation.
 *
 * Le rapport mensuel est généré par le backend (PDF ou DOCX) à partir des
 * mêmes agrégats que l'écran de pilotage — pas d'un export figé. Un
 * rapport recalculé au moment du téléchargement ne peut pas diverger de
 * ce que le comité voit à l'écran, ce qui était le principal reproche
 * fait aux exports manuels.
 *
 * L'aperçu ci-dessous affiche ce que contiendra le fichier, pour éviter
 * de télécharger un document et découvrir qu'on s'est trompé de mois.
 */
export default function ReportsPage() {
  const { month, year, previousMonth, nextMonth, goToCurrent } = usePeriodStore();
  const isCurrent = usePeriodStore((s) => s.isCurrentPeriod());

  const summary = useKpiSummary();
  const sla = useSla();
  // 12 MOIS, soit ~365 lignes journalières regroupées ci-dessous par mois.
  const trend = useKpiTrend(365);

  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null);

  const download = async (format) => {
    setError(null);
    setDownloading(format);
    try {
      const blob = await report.monthly({ month, year, format });
      await saveBlob(blob, `rapport-noc-${year}-${String(month).padStart(2, "0")}.${format}`);
    } catch (downloadError) {
      setError(downloadError.message || errorMessage(downloadError));
    } finally {
      setDownloading(null);
    }
  };

  const kpi = summary.data?.kpi;
  const trendData = monthlyAverages(trend.data ?? []);

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Rapports"
        subtitle="Rapport mensuel d'exploitation, généré à la demande"
        actions={
          <PeriodPicker
            month={month}
            year={year}
            label={monthLabel(month, year)}
            onPrevious={previousMonth}
            onNext={nextMonth}
            onCurrent={goToCurrent}
            isCurrent={isCurrent}
          />
        }
      />

      {error && (
        <Notice tone="error" onClose={() => setError(null)}>
          {error}
        </Notice>
      )}

      <Panel title={`Rapport de ${monthLabel(month, year)}`} accent="var(--accent)">
        <div className="flex items-start gap-4 flex-wrap">
          <FileText size={34} strokeWidth={1.3} style={{ color: "var(--ink-3)" }} />
          <div className="min-w-0 flex-1">
            <p className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
              Synthèse de la disponibilité, des incidents, des causes, du respect des
              engagements de service et des sites les plus affectés. Les fenêtres de
              maintenance planifiée sont exclues de tous les calculs.
            </p>
            {isCurrent && (
              <p className="text-[11.5px] mt-1.5" style={{ color: "var(--sev-medium)" }}>
                Le mois n'est pas clos : le rapport porte sur la période écoulée à
                l'instant du téléchargement. Pour un document contractuel, attendez le
                1er du mois suivant.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-primary"
              disabled={downloading !== null}
              onClick={() => download("pdf")}
            >
              <Download size={13} /> {downloading === "pdf" ? "Génération…" : "PDF"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={downloading !== null}
              onClick={() => download("docx")}
            >
              <Download size={13} /> {downloading === "docx" ? "Génération…" : "Word"}
            </button>
          </div>
        </div>
      </Panel>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat label="Disponibilité" value={pct(kpi?.network_availability_pct, 2)} target="≥ 99 %" />
        <Stat label="Alertes actives (moy.)" value={decimal(kpi?.avg_active_alerts, 1)} />
        <Stat label="Résolus" value={num(kpi?.resolved)} />
        <Stat label="Critiques actives (moy.)" value={decimal(kpi?.avg_active_critical, 1)} />
        <Stat label="MTTR" value={duration(kpi?.avg_mttr_minutes)} target="≤ 4 h" />
        <Stat
          label="Conformité SLA"
          value={pct(sla.data?.global_compliance_pct, 1)}
          target="≥ 95 %"
        />
      </div>

      <Panel title="Historique sur 12 mois" subtitle="ce que couvrent les rapports disponibles">
        <QueryBoundary query={trend} compact emptyMessage="Aucun historique">
          <BarChart
            height={210}
            labels={trendData.map((point) => `${MONTHS_FR_SHORT[point.month - 1]} ${String(point.year).slice(2)}`)}
            legend
            series={[
              {
                label: "Alertes actives (moy.)",
                data: trendData.map((point) => point.avg_alerts),
                color: "var(--sev-high)",
              },
              {
                label: "Critiques actives (moy.)",
                data: trendData.map((point) => point.avg_critical),
                color: "var(--sev-critical)",
              },
            ]}
          />
        </QueryBoundary>
      </Panel>

    </div>
  );
}

/**
 * Moyennes mensuelles à partir des agrégats JOURNALIERS de /kpi/trend.
 *
 * Seuls les jours effectivement collectés comptent : un mois de dix jours de
 * données n'est pas divisé par trente.
 */
function monthlyAverages(days) {
  const months = new Map();
  for (const row of days) {
    if (!row.day) continue;
    const [year, month] = row.day.split("-").map(Number);
    const key = `${year}-${month}`;
    const bucket = months.get(key) ?? { year, month, alerts: [], critical: [] };
    if (row.alerts != null) bucket.alerts.push(row.alerts);
    if (row.critical != null) bucket.critical.push(row.critical);
    months.set(key, bucket);
  }
  const mean = (values) =>
    values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  return [...months.values()]
    .sort((a, b) => a.year - b.year || a.month - b.month)
    .map((bucket) => ({
      year: bucket.year,
      month: bucket.month,
      avg_alerts: mean(bucket.alerts),
      avg_critical: mean(bucket.critical),
    }));
}

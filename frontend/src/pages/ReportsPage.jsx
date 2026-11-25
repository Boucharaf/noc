import { useState } from "react";
import { Download, FileText, Lock } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import { BarChart } from "../components/charts";
import { Notice } from "../components/ui/Controls";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { MONTHS_FR_SHORT, dateTime, decimal, duration, monthLabel, num, pct } from "../lib/format";
import { errorMessage } from "../api/client";
import { report } from "../api/noc";
import { saveBlob } from "../lib/download";
import { useKpiSummary, useKpiTrend, useReportArchive, useSlaIncidents } from "../hooks/queries";
import { usePeriodStore } from "../store/ui";
import { thresholdTarget } from "../lib/vocabulary";

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
  // SLA des tickets iTop ouverts dans le mois choisi (bornes UTC).
  const sla = useSlaIncidents({
    startAt: new Date(Date.UTC(year, month - 1, 1)).toISOString(),
    endAt: new Date(Date.UTC(year, month, 1)).toISOString(),
  });
  const slaTotals = sla.data?.totals;
  // 12 MOIS, soit ~365 lignes journalières regroupées ci-dessous par mois.
  const trend = useKpiTrend(365);

  const [error, setError] = useState(null);
  const [downloading, setDownloading] = useState(null);
  const archive = useReportArchive();
  const [reason, setReason] = useState("");
  const frozen = (archive.data ?? []).some((row) => row.year === year && row.month === month);
  const now = new Date();
  const closed =
    year < now.getUTCFullYear() ||
    (year === now.getUTCFullYear() && month < now.getUTCMonth() + 1);

  const run = async (label, action) => {
    setError(null);
    setDownloading(label);
    try {
      await action();
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setDownloading(null);
    }
  };
  const freeze = () =>
    run("freeze", async () => {
      await report.freeze({ month, year, reason: reason.trim() || null });
      setReason("");
      await archive.refetch();
    });
  const downloadArchived = (row, part) =>
    run(`${part}-${row.id}`, async () => {
      const blob = await report.archived(row.id, part);
      await saveBlob(
        blob,
        `rapport-noc-${row.year}-${String(row.month).padStart(2, "0")}-r${row.revision}.${part}`
      );
    });

  const download = async (format) => {
    setError(null);
    setDownloading(format);
    try {
      if (format === "weekly") {
        const blob = await report.weekly();
        await saveBlob(blob, `rapport-noc-hebdomadaire-${new Date().toISOString().slice(0, 10)}.pdf`);
        return;
      }
      const blob = await report.monthly({ month, year, format });
      await saveBlob(blob, `rapport-noc-${year}-${String(month).padStart(2, "0")}.${format}`);
    } catch (downloadError) {
      setError(errorMessage(downloadError));
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
              <p className="text-[12px] mt-1.5" style={{ color: "var(--sev-medium)" }}>
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

      <Panel
        title="Rapports figés"
        subtitle="chiffres et PDF enregistrés une fois pour toutes, avec leur empreinte"
        accent="var(--accent)"
      >
        {closed && (
          <div className="flex items-center gap-2 flex-wrap mb-2">
            {frozen && (
              <input
                className="input min-w-0 flex-1"
                aria-label="Motif de la révision"
                placeholder="Motif de la révision (obligatoire)"
                maxLength={500}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            )}
            <button
              type="button"
              className="btn"
              disabled={downloading !== null || (frozen && !reason.trim())}
              onClick={freeze}
            >
              <Lock size={13} />{" "}
              {downloading === "freeze"
                ? "Figement…"
                : `${frozen ? "Figer une révision de" : "Figer"} ${monthLabel(month, year)}`}
            </button>
          </div>
        )}
        <QueryBoundary query={archive} compact emptyMessage="Aucun rapport figé">
          <table className="w-full text-[12.5px]">
            <tbody>
              {(archive.data ?? []).map((row) => (
                <tr key={row.id}>
                  <td className="py-1">
                    {monthLabel(row.month, row.year)} · révision {row.revision}
                    {!row.complete && (
                      <span style={{ color: "var(--sev-medium)" }}> · sans iTop</span>
                    )}
                    {row.reason && <span style={{ color: "var(--ink-3)" }}> · {row.reason}</span>}
                  </td>
                  <td style={{ color: "var(--ink-3)" }}>
                    {dateTime(row.generated_at)} · {row.generated_by}
                  </td>
                  <td className="num" title={row.pdf_sha256}>
                    SHA-256 {row.pdf_sha256.slice(0, 12)}…
                  </td>
                  <td className="text-right whitespace-nowrap">
                    {["pdf", "json"].map((part) => (
                      <button
                        key={part}
                        type="button"
                        className="btn"
                        disabled={downloading !== null}
                        onClick={() => downloadArchived(row, part)}
                      >
                        {part === "pdf" ? "PDF" : "Données"}
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryBoundary>
      </Panel>

      {/* AM-27 : le rapport hebdomadaire, téléchargeable et envoyé chaque lundi. */}
      <Panel title="Rapport hebdomadaire" accent="var(--accent)">
        <div className="flex items-start gap-4 flex-wrap">
          <FileText size={34} strokeWidth={1.3} style={{ color: "var(--ink-3)" }} />
          <p className="min-w-0 flex-1 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            Les sept derniers jours en une page : disponibilité, pannes, MTTR et MTBF, incidents
            iTop et respect des SLA, dix équipements les moins disponibles. Envoyé automatiquement
            chaque lundi à 07:00 (GMT) quand l'envoi est activé (WEEKLY_REPORT_ENABLED).
          </p>
          <button
            type="button"
            className="btn btn-primary"
            disabled={downloading !== null}
            onClick={() => download("weekly")}
          >
            <Download size={13} /> {downloading === "weekly" ? "Génération…" : "PDF"}
          </button>
        </div>
      </Panel>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat label="Disponibilité" value={pct(kpi?.network_availability_pct, 2)} target={thresholdTarget("access")} />
        <Stat label="Alertes actives (moy.)" value={decimal(kpi?.avg_active_alerts, 1)} />
        <Stat
          label="Incidents résolus"
          value={num(slaTotals?.resolved)}
          hint={slaTotals ? `sur ${num(slaTotals.incidents)} ticket(s) iTop` : undefined}
        />
        <Stat label="Critiques actives (moy.)" value={decimal(kpi?.avg_active_critical, 1)} />
        <Stat label="MTTR" value={duration(slaTotals?.mttr_minutes)} target="≤ 4 h" />
        <Stat
          label="Conformité SLA"
          value={pct(slaTotals?.compliance_pct, 1)}
          target="≥ 95 %"
        />
      </div>

      <Panel title="Historique sur 12 mois" subtitle="ce que couvrent les rapports disponibles">
        <QueryBoundary query={trend} compact emptyMessage="Aucun historique" minHeight={210}>
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

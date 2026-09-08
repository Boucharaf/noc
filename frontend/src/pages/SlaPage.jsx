import { useState } from "react";
import { Pencil } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat, { Meter } from "../components/ui/Stat";
import { Field, Notice } from "../components/ui/Controls";
import { Modal } from "../components/ui/Overlay";
import { PageHeader, PeriodPicker } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { SeverityBadge } from "../components/ui/Badge";
import { decimal, duration, monthLabel, num, pct } from "../lib/format";
import { severityMeta } from "../lib/vocabulary";
import { errorMessage } from "../api/client";
import { PERMISSIONS } from "../lib/permissions";
import { useSla, useSlaTargets, useUpdateSlaTarget } from "../hooks/queries";
import { usePeriodStore } from "../store/ui";
import { usePermission } from "../hooks/useSession";

/**
 * Engagements de service.
 *
 * Chaque indicateur est affiché avec sa CIBLE et son verdict, jamais
 * seul : c'est la présentation du document métier (« KPI | Cible/Seuil |
 * Réel | Statut »), qui est aussi la seule lisible en comité — un
 * pourcentage sans son objectif ne permet à personne de décider quoi que
 * ce soit.
 *
 * Les objectifs sont modifiables en base (`ops_sla_target`) et non codés
 * en dur : ils sont contractuels et changent au rythme des conventions
 * de service, pas à celui des livraisons logicielles.
 */
export default function SlaPage() {
  const { month, year, previousMonth, nextMonth, goToCurrent } = usePeriodStore();
  const isCurrent = usePeriodStore((s) => s.isCurrentPeriod());
  const canEdit = usePermission(PERMISSIONS.MANAGE_SLA_TARGETS);

  const sla = useSla();
  const targets = useSlaTargets();
  const [editing, setEditing] = useState(null);

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Engagements de service"
        subtitle="Respect des délais de prise en compte et de résolution"
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

      <QueryBoundary query={sla} empty={(d) => !d}>
        {(data) => (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <Stat
                label="Conformité globale"
                value={pct(data.global_compliance_pct, 1)}
                color={
                  data.global_compliance_pct >= 95
                    ? "var(--state-up)"
                    : data.global_compliance_pct >= 85
                      ? "var(--sev-medium)"
                      : "var(--sev-critical)"
                }
                target="≥ 95 %"
              />
              <Stat
                label="Engagements non tenus"
                value={num(data.total_breached, "0")}
                color={data.total_breached ? "var(--sev-critical)" : "var(--state-up)"}
              />
              <Stat
                label="Incidents évalués"
                value={num(
                  data.by_severity.reduce((sum, row) => sum + row.total_incidents, 0),
                  "0",
                )}
                hint="hors maintenance planifiée"
              />
              <Stat
                label="Période"
                value={monthLabel(month, year)}
                compact
                hint={isCurrent ? "mois en cours, non clos" : "mois clos"}
              />
            </div>

            {/* --- Tableau des indicateurs, format « comité » --- */}
            <Panel title="Indicateurs de service" flush>
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Indicateur</th>
                    <th style={{ textAlign: "right", width: 110 }}>Réel</th>
                    <th style={{ textAlign: "right", width: 110 }}>Cible</th>
                    <th style={{ width: 140 }}>Écart</th>
                    <th style={{ width: 120 }}>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {data.indicators.map((indicator) => {
                    const met = indicator.status === "met";
                    // L'écart est ramené à la cible pour que la barre
                    // compare des choses comparables : 2 ms d'écart sur
                    // 100 ms et 2 points sur 95 % ne pèsent pas pareil.
                    const ratio = indicator.target
                      ? Math.min(1, Math.abs(indicator.value / indicator.target))
                      : 0;
                    return (
                      <tr key={indicator.metric}>
                        <td>{indicator.metric}</td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: met ? "var(--state-up)" : "var(--sev-critical)",
                          }}
                        >
                          {decimal(indicator.value, 2)} {indicator.unit}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                          {decimal(indicator.target, 2)} {indicator.unit}
                        </td>
                        <td>
                          <Meter
                            value={ratio * 100}
                            color={met ? "var(--state-up)" : "var(--sev-critical)"}
                            height={5}
                          />
                        </td>
                        <td>
                          <span
                            className="badge"
                            style={{
                              color: met ? "var(--state-up)" : "var(--sev-critical)",
                              background: `color-mix(in srgb, ${
                                met ? "var(--state-up)" : "var(--sev-critical)"
                              } 14%, transparent)`,
                            }}
                          >
                            {met ? "Conforme" : "Non conforme"}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>

            {/* --- Détail par gravité --- */}
            <Panel
              title="Détail par gravité"
              subtitle="délais de prise en compte (MTTA) et de résolution (MTTR)"
              flush
            >
              <table className="tbl">
                <thead>
                  <tr>
                    <th style={{ width: 100 }}>Gravité</th>
                    <th style={{ textAlign: "right" }}>Incidents</th>
                    <th style={{ textAlign: "right" }}>Résolus</th>
                    <th style={{ textAlign: "right" }}>MTTA réel</th>
                    <th style={{ textAlign: "right" }}>Cible MTTA</th>
                    <th style={{ textAlign: "right" }}>MTTR réel</th>
                    <th style={{ textAlign: "right" }}>Cible MTTR</th>
                    <th style={{ textAlign: "right" }}>Respect délai</th>
                    <th style={{ textAlign: "right" }}>Dépassements</th>
                    {canEdit && <th style={{ width: 40 }} />}
                  </tr>
                </thead>
                <tbody>
                  {data.by_severity.map((row) => {
                    const meta = severityMeta(row.severity);
                    const compliant = (row.ttr_compliance_pct ?? 0) >= 95;
                    return (
                      <tr key={row.severity} className={`sev-edge sev-edge-${row.severity}`}>
                        <td>
                          <SeverityBadge severity={row.severity} />
                        </td>
                        <td className="num" style={{ textAlign: "right" }}>
                          {num(row.total_incidents)}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-2)" }}>
                          {num(row.resolved)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color:
                              (row.avg_mtta_minutes ?? 0) > row.tta_target_minutes
                                ? "var(--sev-medium)"
                                : "var(--state-up)",
                          }}
                        >
                          {duration(row.avg_mtta_minutes)}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                          {duration(row.tta_target_minutes)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color:
                              (row.avg_mttr_minutes ?? 0) > row.ttr_target_minutes
                                ? "var(--sev-high)"
                                : "var(--state-up)",
                          }}
                        >
                          {duration(row.avg_mttr_minutes)}
                        </td>
                        <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                          {duration(row.ttr_target_minutes)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: compliant ? "var(--state-up)" : "var(--sev-critical)",
                          }}
                        >
                          {pct(row.ttr_compliance_pct, 1)}
                        </td>
                        <td
                          className="num"
                          style={{
                            textAlign: "right",
                            color: row.breached ? "var(--sev-critical)" : "var(--ink-3)",
                          }}
                        >
                          {num(row.breached, "0")}
                        </td>
                        {canEdit && (
                          <td>
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              title={`Modifier les objectifs « ${meta.label} »`}
                              onClick={() =>
                                setEditing(
                                  (targets.data ?? []).find(
                                    (target) => target.severity === row.severity,
                                  ) ?? {
                                    severity: row.severity,
                                    ttr_target_minutes: row.ttr_target_minutes,
                                    tta_target_minutes: row.tta_target_minutes,
                                    availability_target_pct: 99,
                                  },
                                )
                              }
                            >
                              <Pencil size={12} />
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>
          </>
        )}
      </QueryBoundary>

      <TargetModal target={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

/**
 * Le formulaire est monté à l'ouverture et démonté à la fermeture (le
 * parent ne le rend que si `target` existe), ce qui évite d'avoir à
 * resynchroniser un état local avec la prop : chaque ouverture repart de
 * la valeur en base, sans effet ni dépendance à surveiller.
 */
function TargetModal({ target, onClose }) {
  if (!target) return null;
  return <TargetForm key={target.severity} target={target} onClose={onClose} />;
}

function TargetForm({ target, onClose }) {
  const update = useUpdateSlaTarget();
  const [current, setForm] = useState(target);
  const [error, setError] = useState(null);

  const close = () => {
    setError(null);
    onClose();
  };

  const submit = async () => {
    setError(null);
    try {
      await update.mutateAsync({
        severity: current.severity,
        payload: {
          ttr_target_minutes: Number(current.ttr_target_minutes),
          tta_target_minutes: Number(current.tta_target_minutes),
          availability_target_pct: Number(current.availability_target_pct),
        },
      });
      close();
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open
      onClose={close}
      title={`Objectifs — ${severityMeta(target.severity).label}`}
      subtitle="Ces valeurs servent au calcul de conformité de tous les rapports."
      width={400}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={close}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={submit}
            disabled={update.isPending}
          >
            {update.isPending ? "…" : "Enregistrer"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Délai de prise en compte (MTTA)" hint="En minutes.">
          <input
            className="input"
            type="number"
            min={1}
            value={current.tta_target_minutes}
            onChange={(event) =>
              setForm({ ...current, tta_target_minutes: event.target.value })
            }
          />
        </Field>
        <Field label="Délai de résolution (MTTR)" hint="En minutes.">
          <input
            className="input"
            type="number"
            min={1}
            value={current.ttr_target_minutes}
            onChange={(event) =>
              setForm({ ...current, ttr_target_minutes: event.target.value })
            }
          />
        </Field>
        <Field label="Disponibilité cible" hint="En pourcentage.">
          <input
            className="input"
            type="number"
            step="0.1"
            min={0}
            max={100}
            value={current.availability_target_pct}
            onChange={(event) =>
              setForm({ ...current, availability_target_pct: event.target.value })
            }
          />
        </Field>
      </div>
    </Modal>
  );
}

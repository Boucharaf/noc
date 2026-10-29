import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pencil } from "lucide-react";

import Panel from "../components/ui/Panel";
import Stat from "../components/ui/Stat";
import SlaAtRisk from "../components/domain/SlaAtRisk";
import SlaBreakdown from "../components/domain/SlaBreakdown";
import { BarChart, LineChart } from "../components/charts";
import { complianceColor } from "../lib/itop";
import { Field, Notice, Segmented } from "../components/ui/Controls";
import { Modal } from "../components/ui/Overlay";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { SeverityBadge } from "../components/ui/Badge";
import { duration, num, pct } from "../lib/format";
import { LEVEL } from "../lib/locality";
import { severityMeta } from "../lib/vocabulary";
import { errorMessage } from "../api/client";
import { PERMISSIONS } from "../lib/permissions";
import {
  useSlaContract,
  useSlaIncidents,
  useSlaTargets,
  useUpdateSlaTarget,
} from "../hooks/queries";
import { scopeLabel, useScopeStore } from "../store/scope";
import { usePermission } from "../hooks/useSession";

/**
 * Engagements de service — mesurés sur les INCIDENTS iTop.
 *
 * Délai de prise en charge (TTO) et de résolution (TTR) de chaque ticket,
 * comparés aux objectifs par gravité (`ops_sla_target`, modifiables ici).
 * Ventilation au choix par région, province, site ou équipement, sur le
 * périmètre de la barre commune ; un clic sur une ligne y descend.
 *
 * Chaque taux est affiché avec le nombre d'incidents qui le fondent : un
 * « 100 % » sur un seul ticket ne pèse pas comme sur deux cents.
 */
const GROUPS = ["region", "province", "site", "node"].map((value) => ({
  value,
  label: LEVEL[value].label,
}));

const WINDOWS = [
  { value: 7, label: "7 j" },
  { value: 30, label: "30 j" },
  { value: 90, label: "90 j" },
  { value: 365, label: "12 mois" },
];

/** « sur 2 / 278 tickets · médiane 45 j » : une moyenne dit sur quoi elle porte. */
function delayHint(count, median, total) {
  if (count == null) return undefined;
  if (!count) return "aucun ticket daté dans iTop";
  return `sur ${num(count)}/${num(total)} ticket(s) · médiane ${duration(median)}`;
}

const dateShort = (iso) => (iso ? new Date(iso).toLocaleDateString("fr-FR") : "—");

export default function SlaPage() {
  const navigate = useNavigate();
  const scope = useScopeStore();
  const canEdit = usePermission(PERMISSIONS.MANAGE_SLA_TARGETS);
  const [groupBy, setGroupBy] = useState(
    scope.site ? "node" : scope.province ? "site" : scope.region ? "province" : "region",
  );
  const [days, setDays] = useState(30);

  const sla = useSlaIncidents({ groupBy, days });
  const targets = useSlaTargets();
  const [editing, setEditing] = useState(null);
  const totals = sla.data?.totals;

  const drill = (row) => {
    if (groupBy === "node") {
      if (row.key !== "__none__") navigate(`/equipements/${encodeURIComponent(row.key)}`);
      return;
    }
    if (row.name?.endsWith("non renseignée")) return;
    if (groupBy === "region") {
      scope.setPath({ region: row.name });
      setGroupBy("province");
    } else if (groupBy === "province") {
      scope.setPath({ region: scope.region, province: row.name });
      setGroupBy("site");
    } else {
      scope.setPath({ region: scope.region, province: scope.province, site: row.name });
      setGroupBy("node");
    }
  };

  const targetOf = (severity) =>
    (targets.data ?? []).find((target) => target.severity === severity);

  return (
    <div className="space-y-2">
      <PageHeader
        title="SLA des incidents"
        subtitle={`Tickets iTop ouverts sur ${WINDOWS.find((w) => w.value === days)?.label ?? `${days} j`}${
          sla.data ? ` (du ${dateShort(sla.data.start_at)} au ${dateShort(sla.data.end_at)})` : ""
        } — ${scopeLabel(scope)}`}
        actions={
          <span className="flex items-center gap-2">
            {sla.isPlaceholderData && (
              <span className="text-[11px]" style={{ color: "var(--ink-3)" }} role="status">
                mise à jour…
              </span>
            )}
            <Segmented ariaLabel="Période" options={WINDOWS} value={days} onChange={setDays} />
          </span>
        }
      />

      {sla.isError && (
        <Notice tone="error">
          {sla.error?.response?.data?.detail?.message ?? errorMessage(sla.error)}{" "}
          {sla.error?.response?.data?.detail?.detail}
        </Notice>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Stat
          label="Respect des SLA"
          value={pct(totals?.compliance_pct, 1)}
          color={complianceColor(totals?.compliance_pct)}
          target="≥ 95 %"
          hint={`sur ${num(totals?.evaluated)} incident(s) évalué(s)`}
          gauge={{ value: totals?.compliance_pct, target: 95, max: 100 }}
          help="Part des incidents résolus dans leur délai, parmi les incidents évalués : résolus avec un objectif, ou encore ouverts mais déjà hors délai."
        />
        <Stat
          label="SLA dépassés"
          value={num(totals?.breached)}
          color={totals?.breached ? "var(--sev-critical)" : "var(--state-up)"}
          breakdown={[
            { key: "met", label: "Tenus", value: (totals?.evaluated ?? 0) - (totals?.breached ?? 0), color: "var(--state-up)" },
            { key: "breached", label: "Dépassés", value: totals?.breached ?? 0, color: "var(--sev-critical)" },
            { key: "running", label: "En cours", value: totals?.running ?? 0, color: "var(--accent)" },
          ]}
          help="Incidents résolus après leur objectif, ou encore ouverts alors que l'objectif est déjà dépassé."
        />
        <Stat label="Incidents" value={num(totals?.incidents)} hint={`${num(totals?.resolved)} résolus`} />
        <Stat
          label="En cours, dans les délais"
          value={num(totals?.running)}
          hint="pas encore évalués"
          help="Incidents encore ouverts dont l'objectif n'est pas atteint : ils peuvent encore être tenus, ils ne comptent pas dans le taux."
        />
        <Stat
          label="Prise en charge moy."
          value={duration(totals?.mtto_minutes)}
          help="TTO : temps entre l'ouverture du ticket et son affectation à un agent dans iTop."
          hint={delayHint(totals?.tto_count, totals?.median_tto_minutes, totals?.incidents)}
        />
        <Stat
          label="Résolution moy."
          value={duration(totals?.mttr_minutes)}
          help="TTR : temps entre l'ouverture du ticket et sa résolution dans iTop."
          hint={delayHint(totals?.ttr_count, totals?.median_ttr_minutes, totals?.incidents)}
        />
      </div>

      {/* Les taux ci-dessus racontent le passé ; ceci est encore rattrapable. */}
      <SlaAtRisk limit={10} />

      {sla.data && (
        <div className="grid grid-cols-12 gap-2 items-start">
          <Panel
            title="Évolution du respect des SLA"
            subtitle="par semaine d'ouverture des tickets · ligne pointillée : objectif 95 %"
            className="col-span-12 lg:col-span-7"
          >
            {(sla.data.weekly ?? []).length < 2 ? (
              <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                Moins de deux semaines sur la période : choisir 90 j ou 12 mois pour voir une tendance.
              </p>
            ) : (
              <LineChart
                height={190}
                labels={sla.data.weekly.map((w) => new Date(w.week).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" }))}
                yMin={0}
                yMax={100}
                targetLine={95}
                valueFormatter={(value) => pct(value, 1)}
                series={[
                  {
                    label: "Respect des SLA",
                    data: sla.data.weekly.map((w) => w.compliance_pct),
                    pointCounts: sla.data.weekly.map((w) => w.evaluated),
                    color: "var(--accent)",
                    fill: true,
                  },
                ]}
              />
            )}
          </Panel>
          <Panel
            title="Délais de résolution"
            subtitle="rapportés à l'objectif de chaque gravité"
            className="col-span-12 lg:col-span-5"
          >
            <BarChart
              height={190}
              horizontal
              labels={(sla.data.ttr_distribution ?? []).map((b) => b.label)}
              valueFormatter={(value) => `${num(value)} ticket(s)`}
              series={[
                {
                  label: "Tickets",
                  data: (sla.data.ttr_distribution ?? []).map((b) => b.count),
                  colors: (sla.data.ttr_distribution ?? []).map((b) =>
                    b.key === "le50" || b.key === "le100" ? "var(--state-up)" : "var(--sev-critical)",
                  ),
                },
              ]}
            />
            <p className="text-[11px] mt-1" style={{ color: "var(--ink-3)" }}>
              En vert : résolus dans le délai ; en rouge : hors délai, ou encore ouverts alors que le délai est dépassé.
            </p>
          </Panel>
        </div>
      )}

      <Panel
        title="Respect des SLA par"
        actions={
          <Segmented ariaLabel="Regroupement" options={GROUPS} value={groupBy} onChange={setGroupBy} />
        }
        subtitle="clic sur une ligne pour descendre d'un niveau"
        flush
      >
        <SlaBreakdown query={sla} groupBy={groupBy} onSelect={drill} maxHeight={420} />
      </Panel>

      <Panel title="Par gravité" subtitle="objectifs de prise en charge (TTO) et de résolution (TTR)" flush>
        <QueryBoundary query={sla} compact empty={(d) => !d?.by_severity?.length} emptyMessage="Aucun incident sur la période">
          {(data) => (
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 100 }}>Gravité</th>
                  <th style={{ textAlign: "right" }}>Incidents</th>
                  <th style={{ textAlign: "right" }}>Résolus</th>
                  <th style={{ textAlign: "right" }}>TTO moyen</th>
                  <th style={{ textAlign: "right" }}>Objectif TTO</th>
                  <th style={{ textAlign: "right" }}>TTR moyen</th>
                  <th style={{ textAlign: "right" }}>Objectif TTR</th>
                  <th style={{ textAlign: "right" }}>Respect</th>
                  <th style={{ textAlign: "right" }}>Dépassés</th>
                  {canEdit && <th style={{ width: 40 }} />}
                </tr>
              </thead>
              <tbody>
                {data.by_severity.map((row) => {
                  const goal = data.targets?.[row.severity] ?? {};
                  return (
                    <tr key={row.severity} className={`sev-edge sev-edge-${row.severity}`}>
                      <td>
                        <SeverityBadge severity={row.severity} />
                      </td>
                      <td className="num" style={{ textAlign: "right" }}>{num(row.incidents)}</td>
                      <td className="num" style={{ textAlign: "right" }}>{num(row.resolved)}</td>
                      <td
                        className="num"
                        style={{
                          textAlign: "right",
                          color: row.mtto_minutes != null && goal.tto != null && row.mtto_minutes > goal.tto ? "var(--sev-medium)" : undefined,
                        }}
                      >
                        <span title={delayHint(row.tto_count, row.median_tto_minutes, row.incidents)}>
                          {duration(row.mtto_minutes)}
                        </span>
                      </td>
                      <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>{duration(goal.tto)}</td>
                      <td
                        className="num"
                        style={{
                          textAlign: "right",
                          color: row.mttr_minutes != null && goal.ttr != null && row.mttr_minutes > goal.ttr ? "var(--sev-high)" : undefined,
                        }}
                      >
                        <span title={delayHint(row.ttr_count, row.median_ttr_minutes, row.incidents)}>
                          {duration(row.mttr_minutes)}
                        </span>
                      </td>
                      <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>{duration(goal.ttr)}</td>
                      <td className="num" style={{ textAlign: "right", color: complianceColor(row.compliance_pct) }}>
                        {pct(row.compliance_pct, 1)}
                      </td>
                      <td className="num" style={{ textAlign: "right", color: row.breached ? "var(--sev-critical)" : undefined }}>
                        {num(row.breached)}
                      </td>
                      {canEdit && (
                        <td>
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            title={`Modifier les objectifs « ${severityMeta(row.severity).label} »`}
                            onClick={() =>
                              setEditing(
                                targetOf(row.severity) ?? {
                                  severity: row.severity,
                                  ttr_target_minutes: goal.ttr ?? "",
                                  tta_target_minutes: goal.tto ?? "",
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
          )}
        </QueryBoundary>
      </Panel>

      <ContractPanel goals={sla.data?.targets} />

      <TargetModal target={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

/**
 * Objectifs du NOC face au contrat déclaré dans iTop (SLT). iTop porte le
 * contrat ; le NOC ne s'y aligne pas en silence : un écart se voit ici et
 * se corrige par le crayon du tableau « Par gravité ».
 */
function ContractPanel({ goals }) {
  const contract = useSlaContract();
  const severities = ["critical", "high", "medium", "low"];
  const gap = (noc, itop) =>
    noc != null && itop != null && Math.round(noc) !== Math.round(itop);

  return (
    <Panel
      title="Contrat iTop (SLT)"
      subtitle="engagements déclarés dans iTop, comparés aux objectifs du NOC"
      flush
    >
      <QueryBoundary
        query={contract}
        compact
        empty={(d) => !d?.available || !Object.keys(d.by_severity ?? {}).length}
        emptyMessage="Aucun engagement de service déclaré dans iTop"
        emptyHint={
          contract.data?.reason ??
          "Aucun SLT de type incident n'est défini dans les contrats iTop."
        }
      >
        {(data) => (
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 100 }}>Gravité</th>
                <th style={{ textAlign: "right" }}>TTO iTop</th>
                <th style={{ textAlign: "right" }}>TTO NOC</th>
                <th style={{ textAlign: "right" }}>TTR iTop</th>
                <th style={{ textAlign: "right" }}>TTR NOC</th>
              </tr>
            </thead>
            <tbody>
              {severities.map((severity) => {
                const itop = data.by_severity[severity] ?? {};
                const noc = goals?.[severity] ?? {};
                return (
                  <tr key={severity}>
                    <td>
                      <SeverityBadge severity={severity} />
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>{duration(itop.tto)}</td>
                    <td
                      className="num"
                      style={{
                        textAlign: "right",
                        color: gap(noc.tto, itop.tto) ? "var(--sev-medium)" : "var(--ink-3)",
                      }}
                    >
                      {duration(noc.tto)}
                    </td>
                    <td className="num" style={{ textAlign: "right" }}>{duration(itop.ttr)}</td>
                    <td
                      className="num"
                      style={{
                        textAlign: "right",
                        color: gap(noc.ttr, itop.ttr) ? "var(--sev-medium)" : "var(--ink-3)",
                      }}
                    >
                      {duration(noc.ttr)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </QueryBoundary>
    </Panel>
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
      subtitle="Ces valeurs servent au calcul du respect des SLA des incidents iTop."
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
        <Field label="Délai de prise en charge (TTO)" hint="En minutes.">
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
        <Field label="Délai de résolution (TTR)" hint="En minutes.">
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
        <p className="text-xs text-muted">
          La conformité mesurée ici porte sur les délais de prise en compte et
          de résolution. La disponibilité réseau n'est pas encore mesurée au
          niveau requis pour un engagement SLA.
        </p>
      </div>
    </Modal>
  );
}

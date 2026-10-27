import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import Panel from "../ui/Panel";
import { LineChart } from "../charts";
import { QueryBoundary } from "../ui/States";
import { num, pct } from "../../lib/format";
import { LEVEL } from "../../lib/locality";
import { nodeStateMeta } from "../../lib/vocabulary";
import { useGeoBreakdown, useItopIncidents, useLiveTrend, useNetworkKpi } from "../../hooks/queries";
import { scopeLabel, useScopeStore } from "../../store/scope";

/**
 * États du parc sur 24 h, en aires empilées.
 *
 * Une courbe de disponibilité moyenne reste plate à 99 % quand un site de
 * vingt équipements tombe : la panne se noie dans la moyenne. Empilés, les
 * états montrent la bande rouge des équipements en panne grossir ou
 * maigrir — c'est elle qu'on regarde.
 */
export function FleetStatesChart({ height = 190 }) {
  const trend = useLiveTrend();
  const data = trend.data;
  const labels = (data?.times ?? []).map((at) =>
    new Date(at).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
  );
  const order = ["down", "unknown", "degraded", "maintenance", "up"];

  return (
    <Panel
      title="États du parc sur 24 h"
      subtitle={
        data?.level === "network"
          ? "tout le réseau"
          : `${data?.place ?? ""}${data?.approximate ? " (périmètre élargi à la province)" : ""}`
      }
    >
      <QueryBoundary
        query={trend}
        compact
        empty={(d) => (d?.times?.length ?? 0) < 2}
        emptyMessage="Historique en cours de constitution"
        emptyHint="La courbe apparaît dans quelques minutes."
      >
        <LineChart
          height={height}
          stacked
          legend
          labels={labels}
          valueFormatter={(value) => `${num(value)} équip.`}
          series={order.map((state) => ({
            label: nodeStateMeta(state).label,
            data: data?.states?.[state] ?? [],
            color: nodeStateMeta(state).color,
            width: 1,
          }))}
        />
      </QueryBoundary>
    </Panel>
  );
}

/**
 * Phrase de synthèse en tête des tableaux de bord : ce qu'un exploitant
 * pressé lit en premier. Construite uniquement à partir des chiffres
 * affichés plus bas — elle ne dit rien que l'écran ne montre pas.
 */
export function DashboardSummary() {
  const scope = useScopeStore();
  const network = useNetworkKpi();
  const incidents = useItopIncidents({ limit: 1 });
  const breakdown = useGeoBreakdown();

  const n = network.data;
  const i = incidents.data;
  if (!n) return null;

  const total = n.nodes_total ?? 0;
  const down = n.nodes_down ?? 0;
  const availability = n.availability_pct;
  const worst = [...(breakdown.data?.rows ?? [])]
    .filter((row) => (row.down ?? 0) > 0 && !String(row.name).endsWith("non renseignée"))
    .sort((a, b) => (b.down ?? 0) - (a.down ?? 0))[0];
  const childLevel = breakdown.data?.level;

  const tone =
    availability == null ? "info" : availability >= 99 ? "ok" : availability >= 90 ? "warn" : "bad";
  const Icon = tone === "ok" ? CheckCircle2 : tone === "info" ? Info : AlertTriangle;
  const color = {
    ok: "var(--state-up)",
    warn: "var(--sev-medium)",
    bad: "var(--sev-critical)",
    info: "var(--ink-3)",
  }[tone];

  const parts = [];
  parts.push(
    tone === "ok"
      ? `Réseau normal (${pct(availability, 1)} disponible)`
      : `Réseau ${tone === "bad" ? "fortement perturbé" : "perturbé"} : ${num(down)} équipement(s) hors service sur ${num(total)}`,
  );
  if (worst && tone !== "ok") {
    parts.push(
      `le plus touché : ${worst.name}${childLevel && LEVEL[childLevel] ? ` (${LEVEL[childLevel].label.toLowerCase()})` : ""}, ${num(worst.down)} en panne`,
    );
  }
  if (i) {
    parts.push(
      `${num(i.total)} incident(s) iTop ouvert(s)${i.sla_breached ? `, dont ${num(i.sla_breached)} hors délai` : ""}${
        i.unassigned ? ` et ${num(i.unassigned)} non affecté(s)` : ""
      }`,
    );
  }
  if (n.alerts_critical) parts.push(`${num(n.alerts_critical)} alerte(s) critique(s) dans les outils`);

  return (
    <div
      className="panel flex items-start gap-2 px-3 py-2 text-[12.5px]"
      style={{ borderLeft: `3px solid ${color}` }}
      role="status"
    >
      <Icon size={15} style={{ color, marginTop: 1 }} className="shrink-0" />
      <p className="min-w-0">
        <span className="font-semibold" style={{ color }}>
          {scopeLabel(scope)} —{" "}
        </span>
        {parts.join(" · ")}.
      </p>
    </div>
  );
}

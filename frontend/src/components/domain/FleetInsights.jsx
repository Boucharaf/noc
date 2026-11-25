import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import Panel from "../ui/Panel";
import { LineChart } from "../charts";
import { QueryBoundary } from "../ui/States";
import { num, pct } from "../../lib/format";
import { LEVEL } from "../../lib/locality";
import { nodeStateMeta, THRESHOLDS } from "../../lib/vocabulary";
import {
  useGeoBreakdown,
  useItopIncidents,
  useKpiTrend,
  useLiveTrend,
  useNetworkKpi,
  useSourceHealth,
} from "../../hooks/queries";
import { scopeLabel, useScopeStore } from "../../store/scope";
import { sourcesSentence } from "../../lib/sources";
import { usePermission } from "../../hooks/useSession";
import { PERMISSIONS } from "../../lib/permissions";
import { useWindowStore, windowDays, windowLabel } from "../../store/ui";

/**
 * États du parc sur 24 h, en aires empilées.
 *
 * Une courbe de disponibilité moyenne reste plate à 99 % quand un site de
 * vingt équipements tombe : la panne se noie dans la moyenne. Empilés, les
 * états montrent la bande rouge des équipements en panne grossir ou
 * maigrir — c'est elle qu'on regarde.
 */
export function FleetStatesChart({ height = 190 }) {
  // INC-34 : la courbe suit la période globale. Jusqu'à 24 h, l'historique
  // court (un point par cycle) ; au-delà, les bilans journaliers.
  const hours = useWindowStore((s) => s.hours);
  const daily = hours > 24;
  const live = useLiveTrend();
  const days = useKpiTrend(windowDays(hours));
  const trend = daily ? days : live;
  const data = daily ? toDailyStates(days.data) : live.data;
  const labels = daily
    ? (data?.times ?? []).map((day) =>
        new Date(day).toLocaleDateString("fr-FR", { timeZone: "Africa/Ouagadougou", day: "2-digit", month: "2-digit" }),
      )
    : (data?.times ?? []).map((at) =>
        new Date(at).toLocaleTimeString("fr-FR", { timeZone: "Africa/Ouagadougou", hour: "2-digit", minute: "2-digit" }),
      );
  const order = ["down", "unknown", "degraded", "maintenance", "up"];
  // INC-15 : un périmètre élargi est annoncé en clair, pas en petite note.
  const widened = !daily && data?.approximate;

  return (
    <Panel
      title={`États du parc · ${windowLabel(hours)}`}
      scope={{ period: "window", territorial: true }}
      subtitle={
        daily
          ? "moyenne journalière"
          : widened
            ? `Périmètre élargi : ${data?.place ?? ""} — le site n'a pas d'historique court propre`
            : data?.level === "network"
              ? "tout le réseau"
              : data?.place ?? ""
      }
    >
      <QueryBoundary
        query={trend}
        compact
        minHeight={height}
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

/** Bilans journaliers (kpi_daily) → séries par état, forme de l'historique court. */
function toDailyStates(rows) {
  if (!rows) return rows;
  const states = { down: [], unknown: [], degraded: [], maintenance: [], up: [] };
  for (const row of rows) {
    states.down.push(row.down ?? 0);
    states.degraded.push(row.degraded ?? 0);
    states.up.push(row.up ?? 0);
    // Les bilans ne distinguent pas inconnu et maintenance : le reste du parc.
    states.unknown.push(
      Math.max(0, (row.nodes ?? 0) - (row.up ?? 0) - (row.down ?? 0) - (row.degraded ?? 0)),
    );
    states.maintenance.push(0);
  }
  return { times: rows.map((row) => row.day), states };
}

/**
 * Phrase de synthèse en tête des tableaux de bord : ce qu'un exploitant
 * pressé lit en premier. Construite uniquement à partir des chiffres
 * affichés plus bas — elle ne dit rien que l'écran ne montre pas.
 */
export function DashboardSummary() {
  const scope = useScopeStore();
  const network = useNetworkKpi();
  // L'agent terrain n'a pas accès à /api/incidents (403) : pas de requête.
  const canIncidents = usePermission(PERMISSIONS.VIEW_INCIDENTS);
  const incidents = useItopIncidents({ limit: 1 }, { enabled: canIncidents });
  const breakdown = useGeoBreakdown();
  const health = useSourceHealth();

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
    availability == null
      ? "info"
      : availability >= THRESHOLDS.fleet[0]
        ? "ok"
        : availability >= THRESHOLDS.fleet[1]
          ? "warn"
          : "bad";
  const Icon = tone === "ok" ? CheckCircle2 : tone === "info" ? Info : AlertTriangle;
  const color = {
    ok: "var(--state-up)",
    warn: "var(--sev-medium)",
    bad: "var(--sev-critical)",
    info: "var(--ink-3)",
  }[tone];

  const parts = [];
  const unsupervised = n.nodes_unsupervised ?? 0;
  parts.push(
    tone === "ok"
      ? `Réseau normal (${pct(availability, 1)} du parc supervisé en service)`
      : tone === "info"
        ? // AM-29 : aucun équipement supervisé n'est pas « perturbé ».
          `Aucun équipement supervisé sur ce périmètre (${num(total)} au parc)`
        : `Réseau ${tone === "bad" ? "fortement perturbé" : "perturbé"} : ${num(down)} équipement(s) hors service sur ${num(
            n.nodes_supervised ?? total,
          )} supervisé(s)`,
  );
  if (unsupervised && tone !== "info") {
    parts.push(`${num(unsupervised)} non supervisé(s), comptés à part`);
  }
  if (worst && tone !== "ok") {
    parts.push(
      `le plus touché : ${worst.name}${childLevel && LEVEL[childLevel] ? ` (${LEVEL[childLevel].label.toLowerCase()})` : ""}, ${num(worst.down)} en panne`,
    );
  }
  if (i) {
    parts.push(
      `${num(i.total)} incident(s) iTop ouvert(s)${
        // INC-38 : sans données iTop à jour, le dépassement n'est pas affirmé.
        i.sla_evaluable === false
          ? i.itop_stale
            ? " (délais non évaluables : iTop indisponible)"
            : ""
          : i.sla_breached
            ? `, dont ${num(i.sla_breached)} hors délai`
            : ""
      }${
        i.unassigned ? ` et ${num(i.unassigned)} non affecté(s)` : ""
      }`,
    );
  }
  if (n.alerts_critical) parts.push(`${num(n.alerts_critical)} alerte(s) critique(s) dans les outils`);
  // INC-24 : le bandeau dit quelle source manque et ce qu'elle rend incomplet.
  const sources = sourcesSentence(health.data?.tools);
  if (sources) parts.push(sources);
  const frame = tone === "ok" || tone === "info" ? "var(--accent)" : color;

  return (
    // Zone Z1 (feuille « Design & placement ») : rouge pâle si critique, ambre
    // si dégradé, bleu clair si normal ou non évaluable.
    <div
      className="flex items-center gap-3 px-4 py-3 text-[14px] font-medium"
      style={{
        borderRadius: "var(--radius-lg)",
        border: `1px solid ${frame}`,
        background: `color-mix(in srgb, ${frame} 11%, var(--surface))`,
        minHeight: 64,
      }}
      role="status"
    >
      <Icon size={22} style={{ color }} className="shrink-0" />
      <p className="min-w-0 m-0">
        <span className="font-semibold" style={{ color, fontFamily: "var(--font-display)" }}>
          {scopeLabel(scope)} —{" "}
        </span>
        {parts.join(" · ")}.
      </p>
    </div>
  );
}

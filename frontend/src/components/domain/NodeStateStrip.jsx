import { useMemo } from "react";

import Panel from "../ui/Panel";
import { QueryBoundary } from "../ui/States";
import { smartTime } from "../../lib/format";
import { useNodeSeries } from "../../hooks/queries";

/**
 * Bande d'état sur 7 jours : une case par heure, verte quand l'équipement
 * répondait, rouge quand il était coupé, orange entre les deux, grise sans
 * mesure. Au-dessus, une phrase en clair : « 3 coupures cette semaine,
 * la dernière il y a 2 h ». Lue chez l'outil source (disponibilité ICMP /
 * agent), comme la télémétrie.
 */
const HOURS = 7 * 24;

function colorOf(value) {
  if (value == null) return "var(--surface-3)";
  if (value >= 99) return "var(--state-up)";
  if (value <= 1) return "var(--state-down)";
  return "var(--sev-medium)";
}

export default function NodeStateStrip({ nodeId }) {
  const series = useNodeSeries(nodeId, { metric: "availability_pct", period: "7d" });
  // Sur 7 jours, l'outil rend des moyennes HORAIRES (tendances Zabbix) : une
  // coupure de 6 minutes y devient « 90 % sur l'heure ». Les coupures se
  // comptent donc sur les mesures brutes des dernières 24 h.
  const recent = useNodeSeries(nodeId, { metric: "availability_pct", period: "24h" });

  const { cells, outages, lastOutage, hoursHit, measured } = useMemo(() => {
    const now = Date.now();
    const start = now - HOURS * 3600_000;
    const sums = new Array(HOURS).fill(0);
    const counts = new Array(HOURS).fill(0);
    for (const point of series.data ?? []) {
      const at = Date.parse(point.at ?? point.time);
      if (!Number.isFinite(at) || at < start) continue;
      const index = Math.min(HOURS - 1, Math.floor((at - start) / 3600_000));
      sums[index] += Number(point.value);
      counts[index] += 1;
    }
    const values = sums.map((sum, i) => (counts[i] ? sum / counts[i] : null));
    // Coupures comptées sur les mesures BRUTES : agrégées à l'heure, trois
    // coupures de 6 minutes dans la même heure n'en feraient qu'une.
    let outageCount = 0;
    let last = null;
    let wasDown = false;
    const raw = (recent.data ?? [])
      .map((point) => ({ at: Date.parse(point.at ?? point.time), value: Number(point.value) }))
      .filter((point) => Number.isFinite(point.at))
      .sort((a, b) => a.at - b.at);
    for (const point of raw) {
      const down = point.value < 99;
      if (down && !wasDown) outageCount += 1;
      if (down) last = point.at;
      wasDown = down;
    }
    return {
      cells: values.map((value, i) => ({ value, at: start + i * 3600_000 })),
      outages: outageCount,
      lastOutage: last,
      hoursHit: values.filter((value) => value != null && value < 99).length,
      measured: values.some((value) => value != null),
    };
  }, [series.data, recent.data]);

  const sentence = !measured
    ? "Aucune mesure de disponibilité sur 7 jours."
    : outages === 0 && hoursHit === 0
      ? "Aucune coupure sur les 7 derniers jours."
      : `${outages} coupure${outages > 1 ? "s" : ""} sur les dernières 24 h${
          lastOutage ? `, la dernière ${smartTime(new Date(lastOutage).toISOString())}` : ""
        } · ${hoursHit} heure${hoursHit > 1 ? "s" : ""} touchée${hoursHit > 1 ? "s" : ""} sur 7 jours.`;

  return (
    <Panel title="Disponibilité sur 7 jours" subtitle="une case par heure">
      <QueryBoundary query={series} compact empty={() => false}>
        {() => (
          <>
            <p
              className="text-[12.5px] mb-1.5"
              style={{ color: !measured ? "var(--ink-3)" : outages ? "var(--sev-high)" : "var(--state-up)" }}
            >
              {sentence}
            </p>
            <div className="flex gap-[1px]" style={{ height: 22 }} role="img" aria-label={sentence}>
              {cells.map((cell) => (
                <div
                  key={cell.at}
                  className="flex-1 rounded-[1px]"
                  style={{ background: colorOf(cell.value) }}
                  title={`${new Date(cell.at).toLocaleString("fr-FR", { weekday: "short", hour: "2-digit", minute: "2-digit" })} : ${
                    cell.value == null ? "pas de mesure" : `${cell.value.toFixed(0)} % disponible`
                  }`}
                />
              ))}
            </div>
            <div className="flex justify-between text-[10px] mt-1" style={{ color: "var(--ink-3)" }}>
              <span>il y a 7 jours</span>
              <span className="flex items-center gap-2">
                {[
                  ["var(--state-up)", "disponible"],
                  ["var(--sev-medium)", "coupé une partie de l'heure"],
                  ["var(--state-down)", "coupé toute l'heure"],
                  ["var(--surface-3)", "sans mesure"],
                ].map(([color, label]) => (
                  <span key={label} className="flex items-center gap-1">
                    <span style={{ width: 8, height: 8, background: color, display: "inline-block", borderRadius: 1 }} />
                    {label}
                  </span>
                ))}
              </span>
              <span>maintenant</span>
            </div>
          </>
        )}
      </QueryBoundary>
    </Panel>
  );
}

import { useState } from "react";

import Panel from "../ui/Panel";
import Stat from "../ui/Stat";
import { Segmented } from "../ui/Controls";
import { EmptyState, QueryBoundary } from "../ui/States";
import { dateTime, duration, num, pct } from "../../lib/format";
import { nodeStateMeta, thresholdColor } from "../../lib/vocabulary";
import { useNodeHistory } from "../../hooks/queries";

/**
 * Historique de disponibilité d'un équipement et de ses liens.
 *
 * Lu dans le journal du collecteur (collector/history.py) : périodes d'état
 * et vie des alertes. Le temps non observé (collecteur arrêté, outil muet)
 * est affiché à part ; il ne compte ni pour ni contre la disponibilité.
 */
const HISTORY_WINDOWS = [
  { value: 7, label: "7 j" },
  { value: 30, label: "30 j" },
  { value: 90, label: "90 j" },
  { value: 365, label: "1 an" },
];

/** Frise des états sur la fenêtre ; les trous restent des trous. */
function StateTimeline({ segments, days }) {
  if (!segments?.length) return null;
  const end = Date.now();
  const start = end - days * 86_400_000;
  const span = end - start;
  return (
    <div>
      <div
        className="relative h-3 rounded overflow-hidden"
        style={{ background: "var(--border)" }}
        title="En gris : non observé"
      >
        {segments.map((segment) => {
          const from = Math.max(new Date(segment.start).getTime(), start);
          const to = Math.min(new Date(segment.end).getTime(), end);
          if (to <= from) return null;
          const meta = nodeStateMeta(segment.state);
          return (
            <span
              key={`${segment.start}-${segment.state}`}
              className="absolute top-0 bottom-0"
              style={{
                left: `${((from - start) / span) * 100}%`,
                width: `${Math.max(((to - from) / span) * 100, 0.15)}%`,
                background: meta.color,
              }}
              title={`${meta.label} : ${dateTime(segment.start)} → ${dateTime(segment.end)}`}
            />
          );
        })}
      </div>
      <div className="flex justify-between text-[10.5px] mt-0.5" style={{ color: "var(--ink-3)" }}>
        <span>il y a {days} j</span>
        <span>maintenant</span>
      </div>
    </div>
  );
}

export default function AvailabilityHistory({ nodeId }) {
  const [days, setDays] = useState(30);
  const query = useNodeHistory(nodeId, days);

  return (
    <Panel
      title="Historique de disponibilité"
      subtitle={query.data?.since ? `journal tenu depuis le ${dateTime(query.data.since)}` : undefined}
      actions={<Segmented ariaLabel="Période" value={days} onChange={setDays} options={HISTORY_WINDOWS} />}
    >
      <QueryBoundary
        query={query}
        compact
        empty={(data) => data?.available === false || !data?.node}
        emptyMessage={
          query.data?.available === false ? "Historique indisponible" : "Pas encore d'historique"
        }
        emptyHint={
          query.data?.reason ??
          "Le journal se remplit à chaque cycle de collecte à partir de sa mise en service."
        }
      >
        {(data) => {
          const node = data.node;
          const downMinutes = node.minutes?.down ?? 0;
          return (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <Stat
                  compact
                  label="Disponibilité"
                  value={pct(node.availability_pct, 2)}
                  color={thresholdColor("availability_pct", node.availability_pct) ?? undefined}
                  hint={
                    node.unobserved_minutes
                      ? `${duration(node.unobserved_minutes)} non observées`
                      : "période entièrement observée"
                  }
                />
                <Stat compact label="Hors service" value={duration(downMinutes)} />
                <Stat compact label="Pannes" value={num(node.down_count, "0")} />
                <Stat compact label="Durée moyenne d'une panne" value={duration(node.mttr_minutes)} />
                <Stat
                  compact
                  label="Entre deux pannes (MTBF)"
                  value={node.mtbf_hours != null ? duration(node.mtbf_hours * 60) : "—"}
                />
                <Stat
                  compact
                  label="MTTR des alertes"
                  value={duration(data.alerts?.mttr_minutes)}
                  hint={`${num(data.alerts?.opened, "0")} alerte(s) ouverte(s)`}
                />
              </div>
              <StateTimeline segments={node.segments} days={days} />

              {data.links?.length > 0 && (
                <div>
                  <h3
                    className="text-[10.5px] font-semibold uppercase tracking-[0.07em] mb-1"
                    style={{ color: "var(--ink-3)" }}
                  >
                    Liens surveillés ({data.links.length})
                  </h3>
                  <table className="tbl">
                    <thead>
                      <tr>
                        <th>Lien</th>
                        <th style={{ textAlign: "right" }}>Disponibilité</th>
                        <th style={{ textAlign: "right" }}>Coupé</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.links.slice(0, 12).map((link) => (
                        <tr key={link.subject_id}>
                          <td className="truncate-cell" title={link.name}>
                            {link.name?.split(" — ").slice(1).join(" — ") || link.name}
                          </td>
                          <td
                            className="num"
                            style={{
                              textAlign: "right",
                              color: thresholdColor("availability_pct", link.availability_pct) ?? undefined,
                            }}
                          >
                            {pct(link.availability_pct, 2)}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {duration(link.minutes?.down ?? 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {!data.links?.length && (
                <EmptyState
                  compact
                  message="Aucun lien surveillé"
                  hint="Seuls les liens que NetXMS attend actifs sont suivis un par un."
                />
              )}
            </div>
          );
        }}
      </QueryBoundary>
    </Panel>
  );
}

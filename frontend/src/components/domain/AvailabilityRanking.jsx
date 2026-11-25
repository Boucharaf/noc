import { useState } from "react";
import { Link } from "react-router-dom";

import Panel from "../ui/Panel";
import { Segmented, Toolbar } from "../ui/Controls";
import { QueryBoundary } from "../ui/States";
import { duration, num, pct, availabilityPct } from "../../lib/format";
import { availabilityColor, classHint } from "../../lib/vocabulary";
import { useHistoryRanking, useHistoryStatus } from "../../hooks/queries";
import { useWindowStore, windowDays } from "../../store/ui";

/**
 * Équipements et liens les moins disponibles sur la durée, dans le périmètre
 * de la barre commune — lu dans le journal historique (base du NOC).
 */
const KINDS = [
  { value: "node", label: "Équipements" },
  { value: "link", label: "Liens" },
];


// Équipements dont les pannes sont datées par leur outil source plutôt que
// par les observations du NOC (collector/downtime.py).
const SOURCE_NAMES = {
  netxms_downtime_log: "NetXMS",
  centreon_host_events: "Centreon",
  zabbix_trigger_events: "Zabbix",
  nagios_host_events: "Nagios",
};

function datedBy(sources) {
  const parts = Object.entries(SOURCE_NAMES)
    .filter(([key]) => sources?.[key])
    .map(([key, name]) => `${num(sources[key])} par ${name}`);
  return parts.length ? ` · pannes datées par l'outil : ${parts.join(", ")}` : "";
}

export default function AvailabilityRanking() {
  const [kind, setKind] = useState("node");
  // Période globale (INC-28) : plus de second sélecteur « 7 j → 1 an ».
  const days = windowDays(useWindowStore((s) => s.hours));
  const query = useHistoryRanking({ kind, days, limit: 15 });
  const data = query.data;
  const status = useHistoryStatus();
  const since = status.data?.since ? new Date(status.data.since).toLocaleDateString("fr-FR", { timeZone: "Africa/Ouagadougou" }) : null;

  return (
    <Panel
      title="Les moins disponibles sur la durée"
      scope={{ period: "window", territorial: true }}
      subtitle={
        data?.available
          ? // Disponibilité sur la durée, pondérée par le temps supervisé,
            // avec sa base (INC-01, AM-34).
            `${num(data.subjects)} ${kind === "node" ? "équipement(s)" : "lien(s)"} supervisés · disponibilité ${pct(
              data.average_pct,
              2,
            )} (pondérée)${classHint(data.classes) ? ` · ${classHint(data.classes)}` : ""}${
              data.basis?.unsupervised ? ` · ${num(data.basis.unsupervised)} non supervisé(s), à part` : ""
            }${datedBy(data.basis?.sources)}`
          : "journal historique"
      }
      actions={
        <Toolbar>
          <Segmented ariaLabel="Objet" value={kind} onChange={setKind} options={KINDS} />
        </Toolbar>
      }
      flush
    >
      <QueryBoundary
        query={query}
        compact
        empty={(d) => d?.available === false || !d?.rows?.length}
        emptyMessage={
          data?.available === false
            ? "Historique indisponible"
            : // INC-27 : dire depuis quand le journal se remplit.
              `Historique en construction${since ? ` (collecte depuis le ${since})` : ""}`
        }
        emptyHint={
          data?.reason ??
          (kind === "link"
            ? "Seuls les liens que NetXMS attend actifs sont suivis un par un."
            : "Le journal se remplit à chaque cycle de collecte à partir de sa mise en service.")
        }
      >
        {(d) => (
          <table className="tbl">
            <thead>
              <tr>
                <th>{kind === "node" ? "Équipement" : "Lien"}</th>
                <th>Site</th>
                <th style={{ textAlign: "right" }}>Disponibilité</th>
                <th style={{ textAlign: "right" }}>Hors service</th>
                <th style={{ textAlign: "right" }}>Pannes</th>
                <th style={{ textAlign: "right" }}>Non observé</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((row) => (
                <tr key={row.subject_id}>
                  <td className="truncate-cell" title={row.name}>
                    <Link
                      to={`/equipements/${encodeURIComponent(row.node_id)}`}
                      className="hover:underline"
                    >
                      {row.name}
                    </Link>
                  </td>
                  <td style={{ color: "var(--ink-2)" }}>
                    {row.site ?? "—"}
                    {row.class === "core" && " · cœur"}
                  </td>
                  <td
                    className="num"
                    style={{
                      textAlign: "right",
                      color: availabilityColor(row.availability_pct, row.class ?? "access"),
                    }}
                  >
                    {availabilityPct(row.availability_pct, 2)}
                  </td>
                  <td className="num" style={{ textAlign: "right" }}>
                    {duration(row.minutes?.down ?? 0)}
                  </td>
                  <td className="num" style={{ textAlign: "right" }}>{num(row.down_count, "0")}</td>
                  <td className="num" style={{ textAlign: "right", color: "var(--ink-3)" }}>
                    {duration(row.unobserved_minutes)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </QueryBoundary>
    </Panel>
  );
}

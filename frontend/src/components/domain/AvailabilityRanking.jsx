import { useState } from "react";
import { Link } from "react-router-dom";

import Panel from "../ui/Panel";
import { Segmented, Toolbar } from "../ui/Controls";
import { QueryBoundary } from "../ui/States";
import { duration, num, pct } from "../../lib/format";
import { thresholdColor } from "../../lib/vocabulary";
import { useHistoryRanking } from "../../hooks/queries";

/**
 * Équipements et liens les moins disponibles sur la durée, dans le périmètre
 * de la barre commune — lu dans le journal historique (base du NOC).
 */
const WINDOWS = [
  { value: 7, label: "7 j" },
  { value: 30, label: "30 j" },
  { value: 90, label: "90 j" },
  { value: 365, label: "1 an" },
];
const KINDS = [
  { value: "node", label: "Équipements" },
  { value: "link", label: "Liens" },
];

export default function AvailabilityRanking() {
  const [kind, setKind] = useState("node");
  const [days, setDays] = useState(30);
  const query = useHistoryRanking({ kind, days, limit: 15 });
  const data = query.data;

  return (
    <Panel
      title="Les moins disponibles sur la durée"
      subtitle={
        data?.available
          ? `${num(data.subjects)} ${kind === "node" ? "équipement(s)" : "lien(s)"} suivis · moyenne ${pct(data.average_pct, 2)}`
          : "journal historique"
      }
      actions={
        <Toolbar>
          <Segmented ariaLabel="Objet" value={kind} onChange={setKind} options={KINDS} />
          <Segmented ariaLabel="Période" value={days} onChange={setDays} options={WINDOWS} />
        </Toolbar>
      }
      flush
    >
      <QueryBoundary
        query={query}
        compact
        empty={(d) => d?.available === false || !d?.rows?.length}
        emptyMessage={data?.available === false ? "Historique indisponible" : "Pas encore d'historique"}
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
                  <td style={{ color: "var(--ink-2)" }}>{row.site ?? "—"}</td>
                  <td
                    className="num"
                    style={{
                      textAlign: "right",
                      color: thresholdColor("availability_pct", row.availability_pct) ?? undefined,
                    }}
                  >
                    {pct(row.availability_pct, 2)}
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

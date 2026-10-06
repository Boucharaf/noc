import { useNavigate } from "react-router-dom";

import DataTable from "../ui/Table";
import { NodeStateBadge, StateDot } from "../ui/Badge";
import { Meter } from "../ui/Stat";
import { ageFrom, decimal, num, pct } from "../../lib/format";
import { thresholdColor, toolLabel } from "../../lib/vocabulary";

/**
 * Inventaire des équipements.
 *
 * L'état (`state`) est calculé par le backend, pas ici — voir
 * `node_service._ENRICHED_NODES`. C'est ce qui permet de trier « les plus
 * dégradés d'abord » sur TOUT le parc et pas seulement sur la page
 * affichée : un tri côté client sur 50 lignes sorties d'un ordre
 * alphabétique ne remonterait jamais l'équipement en panne de la page 7.
 *
 * Les colonnes de métriques affichent la DERNIÈRE valeur connue (fenêtre
 * de 6 h). Une case vide y signifie « rien reçu », ce que la colonne
 * « Vu » qualifie explicitement — et ce que l'état « Muet » résume.
 */
function MetricCell({ value, metricType, formatter, showBar = false }) {
  if (value === null || value === undefined) {
    return <span style={{ color: "var(--ink-3)" }}>—</span>;
  }
  const color = thresholdColor(metricType, value);
  return (
    <div className="flex items-center gap-1.5 justify-end">
      {showBar && (
        <div style={{ width: 26 }}>
          <Meter value={value} color={color ?? "var(--accent)"} height={3} />
        </div>
      )}
      <span style={{ color: color ?? "var(--ink-2)" }}>{formatter(value)}</span>
    </div>
  );
}

export default function NodeTable({ nodes, sort, onSort, selectedId, onSelect, variant = "full" }) {
  const navigate = useNavigate();
  const compact = variant === "compact";

  const columns = [
    {
      key: "state",
      header: "État",
      width: compact ? 24 : 116,
      sortKey: compact ? undefined : "state",
      render: (row) =>
        compact ? (
          <StateDot state={row.state} />
        ) : (
          <NodeStateBadge state={row.state} />
        ),
    },
    {
      key: "name",
      header: "Équipement",
      width: compact ? undefined : 210,
      sortKey: compact ? undefined : "name",
      render: (row) => (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="truncate font-medium">{row.name}</span>
          {row.ip_address && !compact && (
            <span className="mono-xs" style={{ color: "var(--ink-3)" }}>
              {row.ip_address}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "locality",
      header: "Site",
      width: 140,
      sortKey: compact ? undefined : "locality",
      render: (row) => (
        <span style={{ color: "var(--ink-2)" }} title={row.region ?? undefined}>
          {row.locality || "—"}
        </span>
      ),
    },
  ];

  if (!compact) {
    columns.push({
      key: "type",
      header: "Type",
      width: 92,
      render: (row) => (
        <span style={{ color: "var(--ink-3)" }}>{row.node_type || "—"}</span>
      ),
    });
    columns.push({
      key: "tools",
      header: "Supervisé par",
      width: 140,
      render: (row) =>
        row.source_tools?.length ? (
          <span className="mono-xs truncate-cell" style={{ color: "var(--ink-3)" }}>
            {row.source_tools.map(toolLabel).join(", ")}
          </span>
        ) : (
          // Un équipement présent dans dim_node sans aucune source est
          // une anomalie de collecte, pas un détail cosmétique.
          <span style={{ color: "var(--sev-medium)" }}>aucune source</span>
        ),
    });
  }

  columns.push(
    {
      key: "availability",
      header: "Dispo.",
      width: 78,
      align: "right",
      mono: true,
      sortKey: compact ? undefined : "availability",
      render: (row) => (
        <MetricCell
          value={row.availability_pct}
          metricType="availability_pct"
          formatter={(v) => pct(v, 1)}
        />
      ),
    },
    {
      key: "latency",
      header: "Latence",
      width: 76,
      align: "right",
      mono: true,
      render: (row) => (
        <MetricCell
          value={row.latency_ms}
          metricType="latency_ms"
          formatter={(v) => `${decimal(v, 0)} ms`}
        />
      ),
    },
    {
      key: "loss",
      header: "Pertes",
      width: 70,
      align: "right",
      mono: true,
      render: (row) => (
        <MetricCell
          value={row.packet_loss_pct}
          metricType="packet_loss_pct"
          formatter={(v) => pct(v, 1)}
        />
      ),
    },
  );

  if (!compact) {
    columns.push(
      {
        key: "cpu",
        header: "CPU",
        width: 84,
        align: "right",
        mono: true,
        render: (row) => (
          <MetricCell
            value={row.cpu_pct}
            metricType="cpu_pct"
            formatter={(v) => pct(v, 0)}
            showBar
          />
        ),
      },
      {
        key: "ram",
        header: "RAM",
        width: 84,
        align: "right",
        mono: true,
        render: (row) => (
          <MetricCell
            value={row.ram_pct}
            metricType="ram_pct"
            formatter={(v) => pct(v, 0)}
            showBar
          />
        ),
      },
    );
  }

  columns.push(
    {
      key: "open",
      header: "Inc. ouv.",
      width: 74,
      align: "right",
      mono: true,
      sortKey: compact ? undefined : "open_incidents",
      render: (row) => (
        <span
          style={{
            color: row.critical_incidents
              ? "var(--sev-critical)"
              : row.open_incidents
                ? "var(--sev-medium)"
                : "var(--ink-3)",
          }}
          title={
            row.critical_incidents
              ? `${row.critical_incidents} critique(s) parmi les incidents ouverts`
              : undefined
          }
        >
          {num(row.open_incidents, "0")}
        </span>
      ),
    },
    {
      key: "seen",
      header: "Vu",
      width: 72,
      align: "right",
      mono: true,
      render: (row) => (
        <span
          style={{ color: row.last_metric_at ? "var(--ink-3)" : "var(--sev-medium)" }}
          title={
            row.last_metric_at
              ? "Dernière métrique reçue"
              : "Aucune métrique reçue depuis plus de 6 h"
          }
        >
          {row.last_metric_at ? ageFrom(row.last_metric_at) : "muet"}
        </span>
      ),
    },
  );

  return (
    <DataTable
      columns={columns}
      rows={nodes ?? []}
      rowKey={(row) => row.node_id}
      sort={sort}
      onSort={onSort}
      selectedKey={selectedId}
      onRowClick={(row) =>
        onSelect ? onSelect(row) : navigate(`/equipements/${row.node_id}`)
      }
    />
  );
}

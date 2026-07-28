import React from "react";
import { Server, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import Card from "./Card";
import { STATUS } from "../theme/colors";

const deriveStatus = (node) => {
  if (node.availability_pct < 90 || node.open >= 3) return "critical";
  if (node.availability_pct < 98 || node.open > 0) return "warning";
  return "ok";
};

const STATUS_ICON = {
  ok: { Icon: CheckCircle2, color: STATUS.good },
  warning: { Icon: AlertTriangle, color: STATUS.warning },
  critical: { Icon: XCircle, color: STATUS.critical },
};

const NodeList = ({ nodes = [], loading }) => (
  <Card
    title="Nœuds du réseau"
    subtitle={`${nodes.length} nœud(s)`}
    bodyClassName="flex min-h-0 flex-1 flex-col p-0"
    className="flex h-full flex-col"
  >
    <ul
      className="h-full divide-y overflow-y-auto"
      style={{ borderColor: "var(--color-border)" }}
    >
      {loading && (
        <li
          className="p-4 text-sm"
          style={{ color: "var(--color-text-muted)" }}
        >
          Chargement…
        </li>
      )}
      {!loading && nodes.length === 0 && (
        <li
          className="p-4 text-sm"
          style={{ color: "var(--color-text-muted)" }}
        >
          Aucun nœud pour cette localité.
        </li>
      )}
      {nodes.map((node) => {
        const { Icon, color } = STATUS_ICON[deriveStatus(node)];
        return (
          <li
            key={node.node_id}
            className="flex items-center justify-between gap-3 p-3.5 transition-colors hover:bg-[var(--color-surface-2)]"
            style={{ borderColor: "var(--color-border)" }}
          >
            <div className="flex min-w-0 items-center gap-3">
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md"
                style={{ background: "var(--color-surface-2)" }}
              >
                <Server
                  className="h-4 w-4"
                  style={{ color: "var(--color-text-muted)" }}
                />
              </div>
              <div className="min-w-0">
                <p
                  className="truncate text-sm font-medium"
                  style={{ color: "var(--color-text-primary)" }}
                >
                  {node.name}
                </p>
                <p
                  className="truncate font-mono text-xs"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {node.code}
                </p>
              </div>
            </div>
            <Icon className="h-5 w-5 shrink-0" style={{ color }} />
          </li>
        );
      })}
    </ul>
  </Card>
);

export default NodeList;

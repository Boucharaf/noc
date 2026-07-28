import React from "react";
import { Activity, Link2, Server, Zap } from "lucide-react";
import Card from "../components/Card";
import TrendLine from "../components/charts/TrendLine";
import { useKpiNodes, useKpiTrend } from "../hooks/useKPI";
import { STATUS } from "../theme/colors";

const TOOLS = [
  {
    key: "zabbix",
    name: "Zabbix",
    icon: Activity,
    description: "Surveillance énergie et onduleurs. Agent actif.",
  },
  {
    key: "nagios",
    name: "Nagios",
    icon: Server,
    description: "Disponibilité hôtes et services via NDO2DB.",
  },
  {
    key: "centreon",
    name: "Centreon / iTop",
    icon: Link2,
    description: "Agrégation des alertes et création de tickets automatique.",
  },
];

const InteropView = () => {
  const { data: nodes = [], isLoading } = useKpiNodes(undefined, 100);
  const { data: trend } = useKpiTrend(6);

  const incidentsByTool = nodes.reduce((acc, n) => {
    acc[n.source_tool] = (acc[n.source_tool] ?? 0) + n.total_incidents;
    return acc;
  }, {});

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-2">
        <Zap className="h-5 w-5" style={{ color: "var(--color-accent)" }} />
        <div>
          <h2
            className="text-xl font-bold"
            style={{ color: "var(--color-text-primary)" }}
          >
            Interopérabilité
          </h2>
          <p
            className="text-sm"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Pipeline collecte → agrégation → ITSM → tableau de bord
          </p>
        </div>
      </div>

      <div className="grid shrink-0 grid-cols-1 gap-4 md:grid-cols-3">
        {TOOLS.map((tool) => (
          <Card key={tool.key} icon={tool.icon} title={tool.name}>
            <p
              className="mb-4 text-sm"
              style={{ color: "var(--color-text-secondary)" }}
            >
              {tool.description}
            </p>
            <div
              className="flex items-center gap-1.5 text-sm font-semibold"
              style={{ color: STATUS.good }}
            >
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: STATUS.good }}
              />
              Connecté
            </div>
            <div
              className="mt-1 text-xs"
              style={{ color: "var(--color-text-muted)" }}
            >
              {isLoading
                ? "Chargement…"
                : `${incidentsByTool[tool.key] ?? 0} incident(s) ce mois-ci`}
            </div>
          </Card>
        ))}
      </div>

      <Card
        title="Disponibilité globale agrégée"
        subtitle="6 derniers mois"
        className="flex min-h-[240px] flex-1 flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
      >
        <div className="h-full min-h-0 flex-1">
          <TrendLine points={trend} />
        </div>
      </Card>
    </div>
  );
};

export default InteropView;

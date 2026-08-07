import React from "react";
import { Activity, Link2, LifeBuoy, Radar, Server, Zap } from "lucide-react";
import Card from "../components/Card";
import TrendLine from "../components/charts/TrendLine";
import { useInteropStatus, useKpiTrend } from "../hooks/useKPI";
import { STATUS } from "../theme/colors";

// One card per tool the ETL can collect from, keyed by the source_tool value
// the backend reports. Descriptions say what this dashboard actually does with
// each tool — not what the tool is capable of — so the page stays honest about
// the integration rather than the product.
const TOOLS = {
  zabbix: {
    name: "Zabbix",
    icon: Activity,
    description: "Problèmes déclencheurs non résolus, via l'API JSON-RPC.",
  },
  nagios: {
    name: "Nagios",
    icon: Server,
    description: "État courant des hôtes, via statusjson.cgi.",
  },
  netxms: {
    name: "NetXMS",
    icon: Radar,
    description: "Alarmes actives, via l'API REST v1.",
  },
  centreon: {
    name: "Centreon",
    icon: Link2,
    description: "Ressources en incident, via l'API REST v2 et les webhooks.",
  },
  itop: {
    name: "iTop",
    icon: LifeBuoy,
    description: "Tickets ouverts, en lecture seule — aucun ticket n'est créé.",
  },
};

// A status the page cannot vouch for must not look like success: anything the
// backend does not positively report as healthy is shown in a colour that
// invites a look, never green.
const STATE_PRESENTATION = {
  ok: { label: "Connecté", color: STATUS.good },
  degraded: { label: "Dégradé", color: STATUS.warning },
  error: { label: "En échec", color: STATUS.critical },
  not_configured: { label: "Non configuré", color: "var(--color-text-muted)" },
  unknown: { label: "Indéterminé", color: STATUS.warning },
};

const ToolCard = ({ tool, entry }) => {
  const meta = TOOLS[entry.tool];
  const presentation =
    STATE_PRESENTATION[entry.state] ?? STATE_PRESENTATION.unknown;

  return (
    <Card key={tool} icon={meta.icon} title={meta.name}>
      <p
        className="mb-4 text-sm"
        style={{ color: "var(--color-text-secondary)" }}
      >
        {meta.description}
      </p>
      <div
        className="flex items-center gap-1.5 text-sm font-semibold"
        style={{ color: presentation.color }}
      >
        <span
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ background: presentation.color }}
        />
        {presentation.label}
      </div>
      {/* A failing collector's detail is the raw API error, which can run to a
          couple of hundred characters. Clamped so one broken tool cannot
          stretch every card in its row; the full text stays in the tooltip. */}
      <div
        className="mt-1 line-clamp-2 break-words text-xs"
        style={{ color: "var(--color-text-muted)" }}
        title={entry.detail}
      >
        {entry.detail}
      </div>
      <div
        className="mt-2 text-xs"
        style={{ color: "var(--color-text-muted)" }}
      >
        {entry.incidents_this_month} incident(s) ce mois-ci
      </div>
    </Card>
  );
};

const InteropView = () => {
  const { data: status, isLoading } = useInteropStatus();
  const { data: trend } = useKpiTrend(6);

  const tools = status?.tools ?? [];
  const lastRun = status?.collected_at
    ? new Date(status.collected_at).toLocaleString("fr-FR")
    : null;

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
            {isLoading
              ? "Pipeline collecte → agrégation → ITSM → tableau de bord"
              : lastRun
                ? `Dernière collecte : ${lastRun}`
                : "Aucune collecte récente — le collecteur est-il actif ?"}
          </p>
        </div>
      </div>

      {/* Five cards, so the column counts are chosen to avoid a row with a
          single orphan: 2 gives 2+2+1, 3 gives 3+2, 5 gives one full row. */}
      <div className="grid shrink-0 grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {tools
          .filter((entry) => TOOLS[entry.tool])
          .map((entry) => (
            <ToolCard key={entry.tool} tool={entry.tool} entry={entry} />
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

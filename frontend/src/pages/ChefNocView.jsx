import React, { useState } from "react";
import { Wifi, WifiOff, Gauge, TrendingUp, Server, PlugZap, ShieldAlert } from "lucide-react";
import Card from "../components/Card";
import KPICard from "../components/KPICard";
import AlertFeed from "../components/AlertFeed";
import NodeList from "../components/NodeList";
import IncidentQueueTable from "../components/IncidentQueueTable";
import NodeDetailDrawer from "../components/NodeDetailDrawer";
import PeriodComparison from "../components/PeriodComparison";
import BurkinaFasoMap from "../components/map/BurkinaFasoMap";
import LocalityBulletList from "../components/map/LocalityBulletList";
import TrendLine from "../components/charts/TrendLine";
import WeeklyBar from "../components/charts/WeeklyBar";
import MTTRDonut from "../components/charts/MTTRDonut";
import HourHeatmap from "../components/charts/HourHeatmap";
import {
  useKpiSummary, useKpiLocalitiesMap, useLocalityNodes, useKpiRecurrent,
  useKpiTrend, useKpiCauses, useHourDistribution, useInteropStatus,
} from "../hooks/useKPI";
import { useNetworkKpi, useNodesDown, useMaintenanceWindows } from "../hooks/useOperational";
import { useIncidentsList, useAcknowledgeIncident, useResolveIncident } from "../hooks/useRealtime";
import { useHasPermission } from "../hooks/usePermission";
import { PERMISSIONS } from "../api/permissions";
import { STATUS } from "../theme/colors";

const NetworkStateStrip = () => {
  const { data: net, isLoading } = useNetworkKpi(24);
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <KPICard title="Disponibilité (24h)" value={net?.availability_pct ?? "—"} unit="%" icon={Wifi} loading={isLoading}
        sentiment={net && net.availability_pct < 99 ? "bad" : "good"} />
      <KPICard title="Perte de paquets" value={net?.packet_loss_pct ?? "—"} unit="%" icon={PlugZap} loading={isLoading}
        sentiment={net && net.packet_loss_pct > 2 ? "bad" : "good"} />
      <KPICard title="Latence moyenne" value={net?.avg_latency_ms ?? "—"} unit="ms" icon={Gauge} loading={isLoading}
        sentiment={net && net.avg_latency_ms > 100 ? "bad" : "good"} />
      <KPICard title="Nœuds injoignables" value={net?.nodes_down ?? "—"} icon={WifiOff} loading={isLoading}
        sentiment={net?.nodes_down > 0 ? "bad" : "good"} accent={STATUS.critical} />
    </div>
  );
};

const EquipementsCritiques = ({ onOpenNode }) => {
  const { data: recurrent = [] } = useKpiRecurrent(3);
  const { data: down = [] } = useNodesDown();
  return (
    <Card title="Équipements critiques" subtitle="Récurrents ce mois-ci et actuellement hors-ligne" bodyClassName="p-0">
      <div className="grid grid-cols-1 divide-y sm:grid-cols-2 sm:divide-x sm:divide-y-0" style={{ borderColor: "var(--color-border)" }}>
        <div className="p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--color-text-secondary)" }}>
            <ShieldAlert className="h-3.5 w-3.5" /> Nœuds récurrents (≥3 incidents)
          </p>
          <ul className="space-y-1.5">
            {recurrent.slice(0, 8).map((n) => (
              <li key={n.node_id}>
                <button onClick={() => onOpenNode(n.code)} className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-[var(--color-surface-2)]">
                  <span className="truncate font-mono text-xs" style={{ color: "var(--color-accent)" }}>{n.code}</span>
                  <span className="truncate flex-1" title={n.name}>{n.name}</span>
                  <span className="shrink-0 font-mono text-xs font-semibold" style={{ color: STATUS.serious }}>{n.total_incidents}</span>
                </button>
              </li>
            ))}
            {recurrent.length === 0 && <li className="text-sm" style={{ color: "var(--color-text-muted)" }}>Aucun nœud récurrent.</li>}
          </ul>
        </div>
        <div className="p-3">
          <p className="mb-2 flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--color-text-secondary)" }}>
            <WifiOff className="h-3.5 w-3.5" /> Hors-ligne actuellement
          </p>
          <ul className="space-y-1.5">
            {down.slice(0, 8).map((n) => (
              <li key={n.node_id}>
                <button onClick={() => onOpenNode(n.node_code)} className="flex w-full items-center justify-between gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-[var(--color-surface-2)]">
                  <span className="truncate font-mono text-xs" style={{ color: STATUS.critical }}>{n.node_code}</span>
                  <span className="truncate flex-1" title={n.node_name}>{n.node_name}</span>
                  <span className="shrink-0 text-xs" style={{ color: "var(--color-text-muted)" }}>{n.locality}</span>
                </button>
              </li>
            ))}
            {down.length === 0 && <li className="text-sm" style={{ color: "var(--color-text-muted)" }}>Aucun nœud hors-ligne.</li>}
          </ul>
        </div>
      </div>
    </Card>
  );
};

const TOOL_LABEL = {
  zabbix: "Zabbix", nagios: "Nagios", netxms: "NetXMS", centreon: "Centreon", itop: "iTop",
};
const STATE_COLOR = {
  ok: STATUS.good, degraded: STATUS.warning, error: STATUS.critical,
  not_configured: "var(--color-text-muted)", unknown: STATUS.warning,
};

const InteropStrip = () => {
  const { data: status } = useInteropStatus();
  const tools = status?.tools ?? [];
  if (tools.length === 0) return null;
  return (
    <Card title="État des collecteurs" subtitle={status?.collected_at ? `Dernière collecte : ${new Date(status.collected_at).toLocaleString("fr-FR")}` : undefined} bodyClassName="flex flex-wrap gap-2 p-3">
      {tools.map((t) => (
        <span
          key={t.tool}
          title={t.detail}
          className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATE_COLOR[t.state] ?? STATUS.warning }} />
          {TOOL_LABEL[t.tool] ?? t.tool}
        </span>
      ))}
    </Card>
  );
};

const MaintenanceStrip = () => {
  const { data: windows = [] } = useMaintenanceWindows();
  const active = windows.filter((w) => new Date(w.ends_at) > new Date());
  if (active.length === 0) return null;
  return (
    <Card title={`Fenêtres de maintenance actives (${active.length})`} bodyClassName="p-3 text-sm">
      <ul className="space-y-1">
        {active.map((w) => (
          <li key={w.id} style={{ color: "var(--color-text-secondary)" }}>
            {w.reason} — jusqu'au {new Date(w.ends_at).toLocaleString("fr-FR")}
          </li>
        ))}
      </ul>
    </Card>
  );
};

const ChefNocView = () => {
  const { data: summary } = useKpiSummary();
  const { data: mapLocalities = [] } = useKpiLocalitiesMap();
  const [selectedLocalityId, setSelectedLocalityId] = useState(null);
  const { data: localityNodes } = useLocalityNodes(selectedLocalityId);
  const [openNode, setOpenNode] = useState(null);

  const { data: trend = [] } = useKpiTrend(6);
  const { data: causes = [] } = useKpiCauses();
  const { data: hours = [] } = useHourDistribution();

  const [statusFilter, setStatusFilter] = useState("open");
  const { data: incidentsPage, isLoading: loadingIncidents } = useIncidentsList({ status: statusFilter, pageSize: 8 });
  const acknowledge = useAcknowledgeIncident();
  const resolve = useResolveIncident();
  const canAck = useHasPermission(PERMISSIONS.ACKNOWLEDGE_INCIDENT);
  const canResolve = useHasPermission(PERMISSIONS.RESOLVE_INCIDENT);

  return (
    <div className="mx-auto max-w-7xl space-y-4">
      <div>
        <h1 className="text-lg font-bold">Vue Chef NOC</h1>
        <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
          {summary?.period.label ?? "—"} · État opérationnel du réseau
        </p>
      </div>

      {/* État du réseau */}
      <NetworkStateStrip />

      <MaintenanceStrip />
      <InteropStrip />

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
        {/* Carte + drill-down localité → nœuds (KPI global → site → équipement) */}
        <Card title="État du réseau — carte" className="xl:col-span-2" bodyClassName="p-3">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
            <div className="lg:col-span-3" style={{ height: 360 }}>
              <BurkinaFasoMap localities={mapLocalities} selectedLocalityId={selectedLocalityId} onSelect={setSelectedLocalityId} />
            </div>
            <div className="lg:col-span-2" style={{ height: 360 }}>
              <LocalityBulletList localities={mapLocalities} selectedLocalityId={selectedLocalityId} onSelect={setSelectedLocalityId} maxHeight="360px" />
            </div>
          </div>
        </Card>

        {/* Alertes */}
        <div style={{ height: 420 }}>
          <AlertFeed />
        </div>
      </div>

      {selectedLocalityId && (
        <div style={{ height: 320 }}>
          <NodeList
            nodes={(localityNodes?.nodes ?? []).map((n) => ({ ...n, node_id: n.node_id }))}
            loading={!localityNodes}
          />
        </div>
      )}

      {/* Incidents en cours */}
      <Card
        icon={Server}
        title="Incidents en cours"
        action={
          <div className="flex gap-1 text-xs">
            {["open", "acknowledged", "resolved"].map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className="rounded-md px-2 py-1 font-medium capitalize"
                style={{
                  background: statusFilter === s ? "var(--color-accent-soft)" : "transparent",
                  color: statusFilter === s ? "var(--color-accent)" : "var(--color-text-secondary)",
                }}
              >
                {s === "open" ? "ouverts" : s === "acknowledged" ? "en charge" : "résolus"}
              </button>
            ))}
          </div>
        }
        bodyClassName="p-0"
      >
        <IncidentQueueTable
          incidents={incidentsPage?.items ?? []}
          total={incidentsPage?.total}
          loading={loadingIncidents}
          canAcknowledge={canAck}
          canResolve={canResolve}
          onAcknowledge={(id) => acknowledge.mutate(id)}
          onResolve={(id, notes) => resolve.mutate({ id, notes })}
          acknowledgingId={acknowledge.isPending ? acknowledge.variables : null}
          resolvingId={resolve.isPending ? resolve.variables?.id : null}
          onOpenNode={setOpenNode}
          compact
        />
      </Card>

      {/* Performance */}
      <div>
        <h2 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--color-text-secondary)" }}>
          <TrendingUp className="h-3.5 w-3.5" /> Performance
        </h2>
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <Card title="Disponibilité — tendance 6 mois" bodyClassName="h-64"><TrendLine points={trend} /></Card>
          <Card title="Incidents résolus / en cours par mois" bodyClassName="h-64"><WeeklyBar points={trend} /></Card>
          <Card title="Répartition par cause" bodyClassName="h-64"><MTTRDonut causes={causes} /></Card>
          <Card title="Distribution horaire des incidents (24h)"><HourHeatmap hours={hours} /></Card>
        </div>
        <div className="mt-3">
          <PeriodComparison />
        </div>
      </div>

      {/* Équipements critiques */}
      <EquipementsCritiques onOpenNode={setOpenNode} />

      {openNode && <NodeDetailDrawer nodeCode={openNode} localityId={selectedLocalityId} onClose={() => setOpenNode(null)} />}
    </div>
  );
};

export default ChefNocView;

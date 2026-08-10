import React from 'react';
import { Database } from 'lucide-react';
import Card from '../components/Card';
import HourHeatmap from '../components/charts/HourHeatmap';
import { useHourDistribution, useKpiRecurrent } from '../hooks/useKPI';
import { STATUS } from '../theme/colors';

// Episode lengths span seconds to months here, so a bare minute count is
// unreadable at both ends.
const formatDuration = (minutes) => {
  if (minutes < 1) return '< 1 min';
  if (minutes < 60) return `${Math.round(minutes)} min`;
  if (minutes < 1440) return `${(minutes / 60).toFixed(1)} h`;
  return `${Math.round(minutes / 1440)} j`;
};

// Deliberately without row counts: they were wrong within a day of the real
// CMDB landing (dim_region said 13, the 2025 découpage made it 17).
const SCHEMA = [
  ['dim_region', 'Régions administratives (découpage 2025)'],
  ['dim_locality', 'Localités et villes, référentiel ANPTIC'],
  ['dim_node', 'Équipements supervisés : CPE, shelters, liaisons PTP, routeurs, switches'],
  ['dim_cause', 'Nature de la panne observée par la supervision'],
  ['fact_incident', 'Table centrale de faits (Tickets, alertes)'],
  ['mv_kpi_node_monthly', 'Vue matérialisée pour KPI rapides'],
];

const DataModelView = () => {
  const { data: hours = [], isLoading: hoursLoading } = useHourDistribution();
  const { data: recurrent = [], isLoading: recurrentLoading } = useKpiRecurrent(3);

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-2">
        <Database className="h-5 w-5" style={{ color: 'var(--color-accent)' }} />
        <h2 className="text-xl font-bold" style={{ color: 'var(--color-text-primary)' }}>Modèle de Données & Analytics</h2>
      </div>

      <div className="grid shrink-0 grid-cols-1 gap-4 lg:grid-cols-2">
        <Card title="Architecture de la Base de Données">
          <ul className="space-y-3">
            {SCHEMA.map(([table, desc]) => (
              <li key={table} className="flex items-start gap-2 text-sm">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--color-accent)' }} />
                <span style={{ color: 'var(--color-text-secondary)' }}>
                  <code className="rounded px-1.5 py-0.5 font-mono text-xs font-semibold" style={{ background: 'var(--color-surface-2)', color: 'var(--color-text-primary)' }}>
                    {table}
                  </code>{' '}
                  : {desc}
                </span>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Distribution H24 (Heatmap)" subtitle="Incidents par heure de détection">
          {hoursLoading ? (
            <div className="flex h-48 items-center justify-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
              Chargement…
            </div>
          ) : (
            <HourHeatmap hours={hours} />
          )}
        </Card>
      </div>

      <Card
        title="Nœuds récurrents"
        subtitle="≥ 3 incidents ce mois — « Instable » = épisodes courts et répétés"
        bodyClassName={`flex min-h-0 flex-1 flex-col ${recurrent.length ? 'p-0' : 'p-5'}`}
        className="flex min-h-[220px] flex-1 flex-col"
      >
        {recurrentLoading && <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Chargement…</p>}
        {!recurrentLoading && recurrent.length === 0 && (
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Aucun nœud récurrent ce mois-ci.</p>
        )}
        {recurrent.length > 0 && (
          <div className="h-full overflow-auto">
            <table className="w-full">
              <thead>
                <tr style={{ color: 'var(--color-text-secondary)' }}>
                  <th className="sticky top-0 z-10 border-b px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>Nœud</th>
                  <th className="sticky top-0 z-10 border-b px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>Localité</th>
                  <th className="sticky top-0 z-10 border-b px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>Épisodes</th>
                  <th className="sticky top-0 z-10 border-b px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide" style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}>Durée moy.</th>
                </tr>
              </thead>
              <tbody>
                {recurrent.map((n) => (
                  <tr key={n.node_id} className="border-t hover:bg-[var(--color-surface-2)]" style={{ borderColor: 'var(--color-border)' }}>
                    <td className="px-4 py-2.5 text-sm" style={{ color: 'var(--color-text-primary)' }}>
                      <span className="font-mono text-xs" style={{ color: 'var(--color-text-secondary)' }}>{n.code}</span> — {n.name}
                    </td>
                    <td className="px-4 py-2.5 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{n.locality}</td>
                    <td className="px-4 py-2.5 text-sm font-bold tabular-nums" style={{ color: STATUS.critical }}>{n.total_incidents}</td>
                    <td className="px-4 py-2.5 text-sm tabular-nums" style={{ color: 'var(--color-text-secondary)' }}>
                      {n.avg_duration_minutes == null ? '—' : formatDuration(n.avg_duration_minutes)}
                      {/* Same incident count, opposite response: a flapping link
                          needs the link fixed, a chronic outage needs someone
                          sent to the site. The count alone cannot tell them apart. */}
                      {n.flapping && (
                        <span
                          className="ml-2 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
                          style={{ background: 'var(--color-accent-soft)', color: 'var(--color-accent)' }}
                        >
                          Instable
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
};

export default DataModelView;

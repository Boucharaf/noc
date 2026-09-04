import { useQuery } from '@tanstack/react-query';

import * as interopApi from '../api/interop';
import * as kpiApi from '../api/kpi';
import * as slaApi from '../api/sla';
import { usePeriodStore } from '../store';

// Chaque queryFn reçoit désormais { signal } de TanStack Query et le
// transmet à axios. Sans ça, changer rapidement de mois/localité sur le
// dashboard laisse les anciennes requêtes courir en arrière-plan et une
// réponse tardive peut écraser un état plus récent à son retour.

export const useKpiSummary = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'summary', year, month],
    queryFn: ({ signal }) => kpiApi.getSummary(month, year, signal),
  });
};

export const useKpiLocalities = (limit = 10) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'localities', year, month, limit],
    queryFn: ({ signal }) => kpiApi.getLocalities(month, year, limit, signal),
  });
};

export const useKpiNodes = (localityId, limit = 10) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'nodes', year, month, localityId, limit],
    queryFn: ({ signal }) => kpiApi.getNodes(month, year, localityId, limit, signal),
  });
};

export const useKpiRecurrent = (minCount = 3) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'recurrent', year, month, minCount],
    queryFn: ({ signal }) => kpiApi.getRecurrent(month, year, minCount, signal),
  });
};

export const useKpiTrend = (months = 6) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'trend', year, month, months],
    queryFn: ({ signal }) => kpiApi.getTrend(month, year, months, signal),
  });
};

export const useHourDistribution = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'hours', year, month],
    queryFn: ({ signal }) => kpiApi.getHourDistribution(month, year, signal),
  });
};

export const useLocalityNodes = (localityId) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'locality-nodes', localityId, year, month],
    queryFn: ({ signal }) => kpiApi.getLocalityNodes(localityId, month, year, signal),
    enabled: !!localityId,
  });
};

export const useKpiCauses = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'causes', year, month],
    queryFn: ({ signal }) => kpiApi.getCauses(month, year, signal),
  });
};

export const useKpiLocalitiesMap = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'localities-map', year, month],
    queryFn: ({ signal }) => kpiApi.getLocalitiesMap(month, year, signal),
  });
};

export const useKpiCompare = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'compare', year, month],
    queryFn: ({ signal }) => kpiApi.getCompare(month, year, signal),
  });
};

// Collector health is liveness, not a KPI: it is refetched on its own short
// interval rather than sitting until the period changes, so a tool that starts
// failing shows up without a reload.
export const useInteropStatus = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['interop', 'status', year, month],
    queryFn: ({ signal }) => interopApi.getInteropStatus(month, year, signal),
    refetchInterval: 30000,
  });
};

export const useSLA = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['sla', year, month],
    queryFn: ({ signal }) => slaApi.getSLA(month, year, signal),
  });
};
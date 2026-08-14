import { useQuery } from '@tanstack/react-query';

import * as interopApi from '../api/interop';
import * as kpiApi from '../api/kpi';
import * as slaApi from '../api/sla';
import { usePeriodStore } from '../store';

export const useKpiSummary = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'summary', year, month],
    queryFn: () => kpiApi.getSummary(month, year),
  });
};

export const useKpiLocalities = (limit = 10) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'localities', year, month, limit],
    queryFn: () => kpiApi.getLocalities(month, year, limit),
  });
};

export const useKpiNodes = (localityId, limit = 10) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'nodes', year, month, localityId, limit],
    queryFn: () => kpiApi.getNodes(month, year, localityId, limit),
  });
};

export const useKpiRecurrent = (minCount = 3) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'recurrent', year, month, minCount],
    queryFn: () => kpiApi.getRecurrent(month, year, minCount),
  });
};

export const useKpiTrend = (months = 6) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'trend', year, month, months],
    queryFn: () => kpiApi.getTrend(month, year, months),
  });
};

export const useHourDistribution = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'hours', year, month],
    queryFn: () => kpiApi.getHourDistribution(month, year),
  });
};

export const useLocalityNodes = (localityId) => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'locality-nodes', localityId, year, month],
    queryFn: () => kpiApi.getLocalityNodes(localityId, month, year),
    enabled: !!localityId,
  });
};

export const useKpiCauses = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'causes', year, month],
    queryFn: () => kpiApi.getCauses(month, year),
  });
};

export const useKpiLocalitiesMap = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'localities-map', year, month],
    queryFn: () => kpiApi.getLocalitiesMap(month, year),
  });
};

export const useKpiCompare = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['kpi', 'compare', year, month],
    queryFn: () => kpiApi.getCompare(month, year),
  });
};

// Collector health is liveness, not a KPI: it is refetched on its own short
// interval rather than sitting until the period changes, so a tool that starts
// failing shows up without a reload.
export const useInteropStatus = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['interop', 'status', year, month],
    queryFn: () => interopApi.getInteropStatus(month, year),
    refetchInterval: 30000,
  });
};

export const useSLA = () => {
  const { month, year } = usePeriodStore();
  return useQuery({
    queryKey: ['sla', year, month],
    queryFn: () => slaApi.getSLA(month, year),
  });
};

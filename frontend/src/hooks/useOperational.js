import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import * as metricsApi from "../api/metrics";
import * as assetsApi from "../api/assets";
import * as maintenanceApi from "../api/maintenance";

// Fenêtre glissante en heures, indépendante du mois sélectionné dans le
// datepicker global : "l'état du réseau" est un indicateur de maintenant,
// pas un rollup calendaire — contrairement aux hooks de useKPI.js.
export const useNetworkKpi = (hours = 24) =>
  useQuery({
    queryKey: ["metrics", "network", hours],
    queryFn: ({ signal }) => metricsApi.getNetworkKpi(hours, signal),
    refetchInterval: 30000,
  });

export const useNodesDown = () =>
  useQuery({
    queryKey: ["metrics", "nodes-down"],
    queryFn: ({ signal }) => metricsApi.getNodesDown(signal),
    refetchInterval: 30000,
  });

export const useCoverage = () =>
  useQuery({
    queryKey: ["assets", "coverage"],
    queryFn: ({ signal }) => assetsApi.getCoverage(signal),
    refetchInterval: 60000,
  });

export const useMaintenanceWindows = () =>
  useQuery({
    queryKey: ["maintenance-windows"],
    queryFn: ({ signal }) => maintenanceApi.getMaintenanceWindows(signal),
    refetchInterval: 60000,
  });

export const useCreateMaintenanceWindow = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: maintenanceApi.createMaintenanceWindow,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["maintenance-windows"] }),
  });
};

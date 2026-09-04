import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as fieldApi from "../api/field";

const POLL_INTERVAL_MS = 30000;

export const useMyInterventions = (status = null) =>
  useQuery({
    queryKey: ["field-interventions", "mine", status],
    queryFn: ({ signal }) => fieldApi.getMyInterventions(status, signal),
    refetchInterval: POLL_INTERVAL_MS,
  });

export const useUpdateInterventionStatus = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ interventionId, status }) =>
      fieldApi.updateInterventionStatus(interventionId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["field-interventions"] });
    },
  });
};

export const useSubmitInterventionReport = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ interventionId, report }) =>
      fieldApi.submitInterventionReport(interventionId, report),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["field-interventions"] });
    },
  });
};

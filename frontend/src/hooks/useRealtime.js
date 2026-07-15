import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import * as alertsApi from '../api/alerts';
import { useAuthStore } from '../store/auth';

const POLL_INTERVAL_MS = 15000;
const WS_RETRY_MS = 10000;

// Pushes /ws/alerts events into the react-query cache: each new incident
// invalidates the alerts + KPI queries so every view refreshes immediately.
const useAlertSocket = () => {
  const queryClient = useQueryClient();
  const token = useAuthStore((state) => state.token);

  useEffect(() => {
    if (!token) return undefined;
    let ws;
    let retryTimer;
    let disposed = false;

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
      ws = new WebSocket(`${proto}://${window.location.host}/ws/alerts?token=${token}`);
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'incident') {
            queryClient.invalidateQueries({ queryKey: ['alerts'] });
            queryClient.invalidateQueries({ queryKey: ['kpi'] });
          }
        } catch {
          // ignore malformed frames (heartbeats are valid JSON, so this is rare)
        }
      };
      ws.onclose = () => {
        if (!disposed) retryTimer = setTimeout(connect, WS_RETRY_MS);
      };
    };

    connect();
    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, [token, queryClient]);
};

// WebSocket push (spec §8.1) with 15s polling kept as fallback for environments
// where the /ws upgrade is blocked.
export const useOpenAlerts = (limit = 20) => {
  useAlertSocket();
  return useQuery({
    queryKey: ['alerts', 'open', limit],
    queryFn: () => alertsApi.getOpenAlerts(limit),
    refetchInterval: POLL_INTERVAL_MS,
  });
};

// Notification bell dropdown: last N critical/high incidents, newest first,
// regardless of status. Shares the same WebSocket invalidation as
// useOpenAlerts (both queries live under the ['alerts', ...] key prefix).
export const useRecentNotifications = (limit = 10) => {
  useAlertSocket();
  return useQuery({
    queryKey: ['alerts', 'recent', limit],
    queryFn: () => alertsApi.getRecentNotifications(limit),
    refetchInterval: POLL_INTERVAL_MS,
  });
};

export const useAcknowledgeIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id) => alertsApi.acknowledgeIncident(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
    },
  });
};

export const useResolveIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, notes }) => alertsApi.resolveIncident(id, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['kpi'] });
    },
  });
};

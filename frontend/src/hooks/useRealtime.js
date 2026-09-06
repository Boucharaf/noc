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
      // Le token n'est plus mis dans l'URL : les query strings de WebSocket
      // finissent typiquement dans les logs d'accès des reverse proxies
      // (nginx, load balancers) en clair — un JWT valide qui traîne dans des
      // logs est une fuite de session, pas un détail. On ouvre la connexion
      // sans credentials puis on s'authentifie via le premier frame envoyé,
      // qui n'est jamais loggé par un proxy L7.
      //
      // ⚠️ Contrepartie backend requise : le handler /ws/alerts doit
      // accepter la connexion en attente d'un premier message
      // {"type":"auth","token":"..."} au lieu de valider un ?token= dans le
      // handshake, et fermer la socket si ce message n'arrive pas sous
      // quelques secondes ou si le token est invalide.
      ws = new WebSocket(`${proto}://${window.location.host}/ws/alerts`);
      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'auth', token }));
      };
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'incident') {
            queryClient.invalidateQueries({ queryKey: ['alerts'] });
            queryClient.invalidateQueries({ queryKey: ['kpi'] });
          } else if (data.type === 'auth_error') {
            // Token rejeté par le backend (expiré entre le rendu et l'ouverture
            // du socket) : pas la peine de retenter avec le même token, autant
            // fermer proprement et laisser le prochain re-render (nouveau
            // token après refresh) rouvrir la connexion.
            ws.close();
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

// WebSocket push, with 15s polling deliberately kept alongside it rather than
// as a replacement: corporate proxies and older reverse-proxy configurations
// silently refuse the /ws upgrade, and a NOC wall display that quietly stopped
// updating is worse than one that updates a little late. The poll is cheap and
// the socket makes it redundant when it works.
export const useOpenAlerts = (limit = 20, localityId = null) => {
  useAlertSocket();
  return useQuery({
    // localityId is part of the key so the map's per-locality panel does not
    // read the global feed's cached rows (and vice versa).
    queryKey: ['alerts', 'open', limit, localityId],
    queryFn: ({ signal }) => alertsApi.getOpenAlerts(limit, localityId, signal),
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
    queryFn: ({ signal }) => alertsApi.getRecentNotifications(limit, signal),
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
    // PermissionError (droit insuffisant, détecté côté client avant l'appel)
    // et 403 (refusé côté serveur) atterrissent tous les deux ici — au
    // composant appelant de lire error.message / error.isForbidden pour
    // afficher le bon message plutôt qu'une erreur générique.
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

// Historique paginé/filtrable (GET /api/incidents) — alimente la file
// d'incidents et l'onglet "Historique", distinct du flux temps réel
// ci-dessus qui ne couvre que les alertes ouvertes.
export const useIncidentsList = (filters = {}) => {
  useAlertSocket();
  return useQuery({
    queryKey: ['incidents', 'list', filters],
    queryFn: ({ signal }) => alertsApi.listIncidents(filters, signal),
    refetchInterval: POLL_INTERVAL_MS,
    placeholderData: (prev) => prev,
  });
};

export const useCreateManualIncident = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: alertsApi.createManualIncident,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['incidents'] });
      queryClient.invalidateQueries({ queryKey: ['kpi'] });
    },
  });
};

// Comptage bon marché (page_size=1, on ne lit que `.total`) pour une tuile KPI
// scoped-période — ex. "incidents critiques ce mois-ci" sur la Vue Décideur,
// qui n'existe pas comme champ direct dans KPISummaryValues.
export const useIncidentsCount = (filters = {}) => {
  return useQuery({
    queryKey: ['incidents', 'count', filters],
    queryFn: async ({ signal }) => {
      const data = await alertsApi.listIncidents({ ...filters, page: 1, pageSize: 1 }, signal);
      return data.total;
    },
  });
};
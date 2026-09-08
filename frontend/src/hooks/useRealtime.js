import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { realtimeUrl } from "../api/config";
import { useAuthStore } from "../store/auth";

/**
 * Flux d'alertes temps réel (WebSocket).
 *
 * Points de conception, chacun issu d'une contrainte du backend
 * (`app/routes/ws.py`) :
 *
 * · L'authentification passe par la PREMIÈRE TRAME, pas par `?token=` :
 *   un navigateur ne peut pas poser d'en-tête Authorization sur une
 *   poignée de main WebSocket, et un jeton dans l'URL finit en clair dans
 *   les journaux du reverse proxy.
 * · Le serveur envoie un ping toutes les 20 s. Si rien n'arrive pendant
 *   plus de 60 s, la socket est considérée morte même si le navigateur
 *   la croit ouverte — cas classique derrière un proxy qui a coupé le
 *   flux sans envoyer de FIN. Sans ce chien de garde, l'écran reste
 *   « connecté » et n'affiche plus rien.
 * · Reconnexion en repli exponentiel plafonné à 30 s : un backend qui
 *   redémarre ne doit pas être martelé par vingt onglets ouverts.
 *
 * Le WebSocket n'est PAS la seule source de vérité : les hooks de
 * `queries.js` continuent d'interroger l'API. La socket sert à réagir
 * dans la seconde ; le poll garantit qu'un écran reste juste même si la
 * socket est tombée sans qu'on s'en aperçoive.
 */

const MAX_EVENTS = 60;
const WATCHDOG_MS = 60_000;
const MAX_BACKOFF_MS = 30_000;

export function useRealtime({ onAlert } = {}) {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();

  const [status, setStatus] = useState("connecting"); // connecting|live|offline
  const [events, setEvents] = useState([]);
  const [lastMessageAt, setLastMessageAt] = useState(null);

  const socketRef = useRef(null);
  const retryRef = useRef(0);
  const watchdogRef = useRef(null);
  const reconnectRef = useRef(null);
  const onAlertRef = useRef(onAlert);
  onAlertRef.current = onAlert;

  const clearTimers = useCallback(() => {
    if (watchdogRef.current) clearTimeout(watchdogRef.current);
    if (reconnectRef.current) clearTimeout(reconnectRef.current);
    watchdogRef.current = null;
    reconnectRef.current = null;
  }, []);

  useEffect(() => {
    if (!token) {
      setStatus("offline");
      return undefined;
    }

    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setStatus((current) => (current === "live" ? current : "connecting"));

      let socket;
      try {
        socket = new WebSocket(realtimeUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;

      const armWatchdog = () => {
        if (watchdogRef.current) clearTimeout(watchdogRef.current);
        watchdogRef.current = setTimeout(() => {
          // Silence prolongé : on ferme nous-mêmes pour forcer le cycle
          // de reconnexion plutôt que d'afficher un faux « live ».
          try {
            socket.close();
          } catch {
            /* déjà fermée */
          }
        }, WATCHDOG_MS);
      };

      socket.onopen = () => {
        socket.send(JSON.stringify({ type: "auth", token }));
        retryRef.current = 0;
        setStatus("live");
        armWatchdog();
      };

      socket.onmessage = (event) => {
        armWatchdog();
        setLastMessageAt(Date.now());

        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }

        if (payload.type === "ping") return;
        if (payload.type === "auth_error") {
          setStatus("offline");
          return;
        }

        setStatus("live");
        setEvents((current) => [payload, ...current].slice(0, MAX_EVENTS));
        onAlertRef.current?.(payload);

        // Une alerte poussée rend immédiatement fausses les vues « temps
        // réel ». On les invalide plutôt que d'insérer l'événement à la
        // main dans le cache : le backend calcule des compteurs dérivés
        // (non assignés, plus ancien non acquitté) qu'on ne saurait pas
        // recalculer correctement côté client.
        queryClient.invalidateQueries({ queryKey: ["alerts"] });
        queryClient.invalidateQueries({ queryKey: ["incidents"] });
        queryClient.invalidateQueries({ queryKey: ["nodes"] });
      };

      socket.onerror = () => {
        /* onclose suit toujours : la reconnexion est traitée là. */
      };

      socket.onclose = () => {
        if (disposed) return;
        setStatus("offline");
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      const attempt = Math.min(retryRef.current++, 6);
      const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS);
      reconnectRef.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      disposed = true;
      clearTimers();
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket && socket.readyState <= WebSocket.OPEN) socket.close();
    };
  }, [token, queryClient, clearTimers]);

  return { status, events, lastMessageAt };
}

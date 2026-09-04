import { useCallback, useEffect, useRef } from "react";
import { useAuthStore } from "../store/auth";

// Renew once the token is inside this window of expiring.
const RENEW_WHEN_REMAINING_MS = 5 * 60 * 1000;
const CHECK_INTERVAL_MS = 60 * 1000;

/**
 * Keeps the session alive while the dashboard is being used.
 *
 * Renewal is time-based rather than tied to request failures: waiting for a
 * 401 means the session is already dead. This hook now delegates the actual
 * network call to useAuthStore.refresh(), the same deduped function the
 * axios 401 interceptor in api/client.js uses — so a proactive renewal and a
 * reactive one triggered by a stray 401 can never fire two concurrent
 * /auth/refresh calls (important once the refresh token rotates on use:
 * a race there would invalidate one of the two and force a false logout).
 */
export const useSessionKeepAlive = () => {
  const token = useAuthStore((s) => s.token);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const renewing = useRef(false);

  const maybeRenew = useCallback(async () => {
    const state = useAuthStore.getState();
    if (!state.token || renewing.current) return;
    const remaining = state.expiresAt ? state.expiresAt - Date.now() : 0;
    if (remaining > RENEW_WHEN_REMAINING_MS) return;

    renewing.current = true;
    try {
      await state.refresh();
    } catch {
      // Cookie de refresh absent/expiré/révoqué : le store est déjà passé
      // en logout("expired") par refresh(), rien à faire de plus ici.
    } finally {
      renewing.current = false;
    }
  }, []);

  useEffect(() => {
    if (!token) return undefined;

    const interval = setInterval(maybeRenew, CHECK_INTERVAL_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") maybeRenew();
    };
    document.addEventListener("visibilitychange", onVisible);
    maybeRenew();

    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [token, expiresAt, maybeRenew]);
};
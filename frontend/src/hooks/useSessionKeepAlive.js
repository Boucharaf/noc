import { useCallback, useEffect, useRef } from "react";
import { refreshSession } from "../api/auth";
import { useAuthStore } from "../store/auth";

// Renew once the token is inside this window of expiring. Comfortably longer
// than any plausible clock skew or request delay, and short enough that a
// 30-minute token is renewed roughly twice an hour rather than constantly.
const RENEW_WHEN_REMAINING_MS = 5 * 60 * 1000;
const CHECK_INTERVAL_MS = 60 * 1000;

/**
 * Keeps the session alive while the dashboard is being used.
 *
 * The token lasts 30 minutes and nothing renewed it, so an operator watching
 * the wall display was dropped to the login screen mid-shift — and, because a
 * 401 logs out silently, without any explanation. Polling every 15s kept the
 * data fresh but did nothing for the credential behind it.
 *
 * Renewal is time-based rather than tied to request failures: waiting for a
 * 401 means the session is already dead, and at that point the only cure is a
 * new login. The session still lapses normally once the tab is closed or the
 * machine sleeps past expiry, which is the point — this extends an active
 * session, it does not make one permanent.
 */
export const useSessionKeepAlive = () => {
  const token = useAuthStore((s) => s.token);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const login = useAuthStore((s) => s.login);
  // Guards against a second renewal starting while the first is in flight —
  // the interval and the visibility handler can otherwise fire together.
  const renewing = useRef(false);

  const maybeRenew = useCallback(async () => {
    const state = useAuthStore.getState();
    if (!state.token || renewing.current) return;
    // No expiry recorded (a session from before this existed): renew once so
    // the store picks one up, rather than never renewing at all.
    const remaining = state.expiresAt ? state.expiresAt - Date.now() : 0;
    if (remaining > RENEW_WHEN_REMAINING_MS) return;

    renewing.current = true;
    try {
      const data = await refreshSession();
      login(data.access_token, data.user, data.expires_in);
    } catch {
      // Already expired or revoked. The client's 401 interceptor logs out; a
      // failure here needs no separate handling.
    } finally {
      renewing.current = false;
    }
  }, [login]);

  useEffect(() => {
    if (!token) return undefined;

    const interval = setInterval(maybeRenew, CHECK_INTERVAL_MS);
    // A backgrounded tab throttles timers heavily, so the interval alone can
    // let a session lapse while nobody is looking. Re-check on the way back.
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

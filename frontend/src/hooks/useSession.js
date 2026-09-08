import { useEffect } from "react";

import { useAuthStore } from "../store/auth";
import { usePeriodStore, useUiStore } from "../store/ui";
import { hasPermission } from "../lib/permissions";

/** Restaure la session au démarrage à partir du cookie de refresh. */
export function useSessionBootstrap() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  const bootstrapped = useAuthStore((s) => s.bootstrapped);

  useEffect(() => {
    if (!bootstrapped) bootstrap();
  }, [bootstrap, bootstrapped]);

  return bootstrapped;
}

/**
 * Renouvellement proactif du jeton d'accès.
 *
 * Sans lui, un écran de supervision laissé ouvert sans interaction voit
 * son jeton expirer (30 min), puis rafraîchit sur le premier 401 — ce qui
 * fait clignoter tous les widgets en erreur pendant un instant. On
 * renouvelle donc 2 minutes AVANT l'expiration, quand l'écran est visible.
 */
export function useSessionKeepAlive() {
  const token = useAuthStore((s) => s.token);
  const expiresAt = useAuthStore((s) => s.expiresAt);
  const refresh = useAuthStore((s) => s.refresh);

  useEffect(() => {
    if (!token || !expiresAt) return undefined;

    const margin = 120_000;
    const delay = Math.max(10_000, expiresAt - Date.now() - margin);

    const timer = setTimeout(() => {
      // Onglet en arrière-plan : inutile de tenir la session éveillée, le
      // refresh se fera au retour ou sur le premier 401.
      if (document.visibilityState === "visible") refresh().catch(() => {});
    }, delay);

    return () => clearTimeout(timer);
  }, [token, expiresAt, refresh]);
}

/**
 * Bascule automatique de la période au changement de mois.
 *
 * Un dashboard reste ouvert des semaines sur un écran mural : sans cette
 * vérification, il continuerait d'afficher les KPI du mois précédent le
 * 1er au matin. Un test par minute suffit et ne coûte rien.
 */
export function usePeriodAutoSync() {
  const syncToCurrent = usePeriodStore((s) => s.syncToCurrent);

  useEffect(() => {
    const timer = setInterval(syncToCurrent, 60_000);
    return () => clearInterval(timer);
  }, [syncToCurrent]);
}

/** Applique le thème choisi à <html> et à la barre d'adresse mobile. */
export function useThemeEffect() {
  const theme = useUiStore((s) => s.theme);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("light", theme === "light");
    root.style.colorScheme = theme === "light" ? "light" : "dark";
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", theme === "light" ? "#eef1f6" : "#0a0d14");
  }, [theme]);
}

/** `true` si le rôle courant possède la permission donnée. */
export function usePermission(permission) {
  const role = useAuthStore((s) => s.user?.role);
  return hasPermission(role, permission);
}

export function useCurrentUser() {
  return useAuthStore((s) => s.user);
}

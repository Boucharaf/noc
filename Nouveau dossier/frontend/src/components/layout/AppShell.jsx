import { useCallback, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import AlertTicker from "./AlertTicker";
import ErrorBoundary from "../ui/ErrorBoundary";
import SideNav from "./SideNav";
import TopBar from "./TopBar";
import { PERMISSIONS, hasPermission, homeRoute } from "../../lib/permissions";
import { useAuthStore } from "../../store/auth";
import { useHealth, useInterop } from "../../hooks/queries";
import { useRealtime } from "../../hooks/useRealtime";

/**
 * Coque de l'application.
 *
 * Deux décisions structurantes :
 *
 * 1. UN SEUL WebSocket pour toute l'application, ouvert ici et jamais
 *    dans une page. Chaque page qui ouvrirait le sien multiplierait les
 *    connexions à chaque navigation, et le backend verrait autant
 *    d'abonnés Redis que d'écrans visités depuis le chargement.
 * 2. La coque ne défile pas — seul `<Outlet>` défile. Le bandeau d'état
 *    et le ticker d'alertes doivent rester visibles même au milieu d'un
 *    tableau de 200 lignes ; c'est toute la différence entre une console
 *    de supervision et un site web.
 */
export default function AppShell() {
  const role = useAuthStore((s) => s.user?.role);
  const location = useLocation();
  const health = useHealth();
  const canSeeInterop = hasPermission(role, PERMISSIONS.VIEW_INTEROP);
  const interop = useInterop({ enabled: canSeeInterop });

  // Signal sonore d'alerte critique : volontairement produit par
  // l'AudioContext du navigateur plutôt que par un fichier audio. Un .mp3
  // impose un asset, un préchargement et une politique d'autoplay ; deux
  // oscillateurs de 180 ms ne demandent rien et se déclenchent après la
  // première interaction de l'utilisateur, ce qui est justement la
  // contrainte des navigateurs.
  const audioRef = useRef(null);
  const chime = useCallback(() => {
    try {
      const AudioCtor = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtor) return;
      audioRef.current ??= new AudioCtor();
      const context = audioRef.current;
      if (context.state === "suspended") return; // pas encore d'interaction
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(880, context.currentTime);
      oscillator.frequency.setValueAtTime(660, context.currentTime + 0.09);
      gain.gain.setValueAtTime(0.0001, context.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.13, context.currentTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.2);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + 0.22);
    } catch {
      /* audio indisponible : l'alerte visuelle suffit */
    }
  }, []);

  const { status: realtimeStatus } = useRealtime({
    onAlert: (payload) => {
      if (payload?.severity === "critical") chime();
    },
  });

  const toolsDown = interop.data
    ? interop.data.tools_total - interop.data.tools_healthy
    : 0;

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <TopBar
        realtimeStatus={realtimeStatus}
        health={health.data}
        toolsHealthy={interop.data?.tools_healthy ?? 0}
        toolsTotal={interop.data?.tools_total ?? 0}
        canSeeIncidents={hasPermission(role, PERMISSIONS.VIEW_INCIDENTS)}
      />
      <div className="flex-1 flex min-h-0">
        <div className="hidden md:flex">
          <SideNav role={role} toolsDown={toolsDown} />
        </div>
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <AlertTicker />
          <main className="flex-1 min-h-0 overflow-y-auto p-2.5">
            {/* La frontière entoure UNIQUEMENT le contenu de page : si un
                écran plante, la barre d'état, le ticker et la navigation
                restent debout. C'est la différence entre « un écran est
                en panne » et « le NOC n'a plus d'interface ». */}
            <ErrorBoundary resetKey={location.pathname}>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </div>
      <MobileNav role={role} />
    </div>
  );
}

/**
 * Barre d'onglets mobile.
 *
 * Le rail latéral disparaît sous 768 px : sur téléphone, c'est l'agent
 * terrain qui utilise l'application, debout devant une baie. Quatre
 * cibles tactiles suffisent — sa tournée, les alertes, le parc, son
 * compte — et elles doivent être atteignables au pouce, donc en bas.
 */
function MobileNav({ role }) {
  const items = [
    // L'accueil suit le rôle : envoyer un directeur sur /console lui
    // afficherait un écran interdit alors qu'il a le sien.
    { to: homeRoute(role), label: "Accueil" },
    { to: "/equipements", label: "Parc" },
    { to: "/carte", label: "Carte" },
    { to: "/compte", label: "Compte" },
  ];

  return (
    <nav
      className="md:hidden shrink-0 flex border-t"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className="flex-1 text-center py-2 text-[11px]"
          style={({ isActive }) => ({
            color: isActive ? "var(--accent-ink)" : "var(--ink-2)",
            textDecoration: "none",
            fontWeight: isActive ? 600 : 400,
          })}
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

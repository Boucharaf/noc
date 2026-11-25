import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { BellRing, Home, Menu, Router, X } from "lucide-react";

import ScopeBar from "./ScopeBar";
import ErrorBoundary from "../ui/ErrorBoundary";
import SideNav from "./SideNav";
import TopBar from "./TopBar";
import { PERMISSIONS, hasPermission, homeRoute } from "../../lib/permissions";
import { useAuthStore } from "../../store/auth";
import { useHealth, useInterop } from "../../hooks/queries";
import MonthView from "../../pages/MonthView";
import { MONTH_ROUTES, usePeriodStore } from "../../store/ui";
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
// Écrans qui suivent le périmètre (recherche + localité). Les écrans
// d'administration (comptes, collecte) n'en ont pas l'usage. Maintenances et
// interventions le suivent : sans la barre, un filtre choisi ailleurs s'y
// appliquerait sans qu'on le voie.
const SCOPED_ROUTES = [
  "/maintenances",
  "/interventions",
  "/direction",
  "/supervision",
  "/console",
  "/territoire",
  "/incidents",
  "/alertes",
  "/equipements",
  "/performance",
  "/sla",
];

export default function AppShell() {
  const role = useAuthStore((s) => s.user?.role);
  const location = useLocation();
  const liveMonth = usePeriodStore((s) => s.isCurrentPeriod());
  const pastMonth = !liveMonth && MONTH_ROUTES.includes(location.pathname);
  const health = useHealth();
  // Tiroir de navigation (téléphone) : fermé à chaque changement d'écran et
  // par Échap.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => setMenuOpen(false), [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return undefined;
    const onKey = (event) => event.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);
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
      {/* AM-26 : premier élément au clavier, pour sauter l'en-tête et le menu. */}
      <a href="#contenu" className="skip-link">Aller au contenu</a>
      {/* Maquette ANPTIC : barre latérale marine sur toute la hauteur, logo
          en tête ; l'en-tête, les filtres et le contenu occupent la droite. */}
      <div className="flex-1 flex min-h-0">
        <div className="hidden md:flex h-full">
          <SideNav
            role={role}
            toolsDown={toolsDown}
            toolsTotal={interop.data?.tools_total ?? 0}
          />
        </div>
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <TopBar
            realtimeStatus={realtimeStatus}
            health={health.data}
            toolsHealthy={interop.data?.tools_healthy ?? 0}
            toolsTotal={interop.data?.tools_total ?? 0}
            onMenu={() => setMenuOpen(true)}
          />
          {SCOPED_ROUTES.some((prefix) => location.pathname.startsWith(prefix)) && <ScopeBar />}
          <main id="contenu" tabIndex={-1} className="flex-1 min-h-0 overflow-y-auto px-5 pt-4 pb-10">
            {/* La frontière entoure UNIQUEMENT le contenu de page : si un
                écran plante, la barre d'état, le ticker et la navigation
                restent debout. C'est la différence entre « un écran est
                en panne » et « le NOC n'a plus d'interface ». */}
            <ErrorBoundary resetKey={location.pathname}>
              {pastMonth ? <MonthView /> : <Outlet />}
            </ErrorBoundary>
          </main>
        </div>
      </div>
      {menuOpen && (
        <div className="nav-drawer md:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="nav-drawer-backdrop" onClick={() => setMenuOpen(false)} />
          <div className="nav-drawer-panel side-nav">
            <div
              className="flex items-center justify-between px-3 border-b shrink-0"
              style={{ height: "var(--topbar-h)", borderColor: "var(--rail-border)" }}
            >
              <span className="text-[12px] font-semibold uppercase tracking-[0.07em]" style={{ color: "var(--rail-ink-2)" }}>
                Menu
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setMenuOpen(false)}
                aria-label="Fermer le menu"
                autoFocus
              >
                <X size={16} />
              </button>
            </div>
            <SideNav
              role={role}
              toolsDown={toolsDown}
              toolsTotal={interop.data?.tools_total ?? 0}
              onNavigate={() => setMenuOpen(false)}
              expanded
            />
          </div>
        </div>
      )}
      <MobileNav role={role} onMenu={() => setMenuOpen(true)} />
    </div>
  );
}

/**
 * Barre d'onglets mobile.
 *
 * Le rail latéral disparaît sous 768 px. Les écrans les plus consultés
 * debout devant une baie restent à un pouce, en bas ; « Menu » ouvre le
 * tiroir qui donne accès à TOUS les écrans permis au rôle (avant, un
 * téléphone n'atteignait que quatre écrans).
 */
function MobileNav({ role, onMenu }) {
  const items = [
    // L'accueil suit le rôle : envoyer un directeur sur /console lui
    // afficherait un écran interdit alors qu'il a le sien.
    { to: homeRoute(role), label: "Accueil", icon: Home, end: true },
    { to: "/alertes", label: "Alertes", icon: BellRing, permission: PERMISSIONS.VIEW_ALERTS },
    { to: "/equipements", label: "Parc", icon: Router, permission: PERMISSIONS.VIEW_NODES },
  ].filter((item) => !item.permission || hasPermission(role, item.permission));

  const tab = "flex-1 flex flex-col items-center justify-center gap-0.5 py-1.5 text-[12px] min-h-[48px]";
  return (
    <nav
      className="mobile-tabbar md:hidden shrink-0 flex border-t"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      aria-label="Navigation rapide"
    >
      {items.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={tab}
            style={({ isActive }) => ({
              color: isActive ? "var(--accent-ink)" : "var(--ink-2)",
              textDecoration: "none",
              fontWeight: isActive ? 600 : 400,
            })}
          >
            <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
            {item.label}
          </NavLink>
        );
      })}
      <button type="button" className={tab} style={{ color: "var(--ink-2)" }} onClick={onMenu}>
        <Menu size={17} strokeWidth={1.8} aria-hidden="true" />
        Menu
      </button>
    </nav>
  );
}

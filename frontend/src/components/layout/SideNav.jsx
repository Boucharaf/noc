import {
  Activity,
  BellRing,
  CalendarClock,
  FileBarChart,
  Gauge,
  LayoutDashboard,
  MapPinned,
  Plug,
  Radio,
  Router,
  ScrollText,
  Truck,
  UserCog,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { PERMISSIONS, hasPermission, homeRoute } from "../../lib/permissions";
import { useOverview } from "../../hooks/queries";
import { useUiStore } from "../../store/ui";
import { scopeLabel, useScopeStore } from "../../store/scope";

/**
 * Navigation latérale.
 *
 * Organisée par MOMENT D'USAGE et non par entité technique :
 * « Temps réel » (ce qui se passe maintenant), « Analyse » (ce qui s'est
 * passé), « Exploitation » (ce qui est planifié), « Administration ».
 * Un exploitant qui prend son poste va d'abord au premier groupe ; un
 * directeur qui prépare un comité va directement au deuxième. Ranger par
 * table (« Incidents », « Nœuds », « Métriques ») obligerait les deux à
 * traverser tout le menu.
 *
 * Les compteurs affichés à droite de certaines entrées ne sont pas
 * décoratifs : ils évitent d'ouvrir un écran pour découvrir qu'il est
 * vide, et signalent une file qui gonfle pendant qu'on regarde ailleurs.
 */

const SECTIONS = [
  {
    title: "Temps réel",
    items: [
      { to: "__home__", label: "Tableau de bord", icon: LayoutDashboard },
      {
        to: "/territoire",
        label: "Territoire",
        icon: MapPinned,
        permission: PERMISSIONS.VIEW_MAP,
      },
      // Incidents = tickets iTop ; alertes = signaux des outils de
      // supervision. Deux files distinctes, deux entrées distinctes.
      {
        to: "/incidents",
        label: "Incidents iTop",
        icon: Radio,
        permission: PERMISSIONS.VIEW_INCIDENTS,
        badge: "openIncidents",
      },
      {
        to: "/alertes",
        label: "Alertes outils",
        icon: BellRing,
        permission: PERMISSIONS.VIEW_ALERTS,
        badge: "openAlerts",
      },
      {
        to: "/equipements",
        label: "Équipements",
        icon: Router,
        permission: PERMISSIONS.VIEW_NODES,
        badge: "nodesDown",
      },
    ],
  },
  {
    title: "Analyse",
    items: [
      { to: "/performance", label: "Performance réseau", icon: Activity, permission: PERMISSIONS.VIEW_METRICS },
      { to: "/sla", label: "SLA & disponibilité", icon: Gauge, permission: PERMISSIONS.VIEW_SLA },
      { to: "/rapports", label: "Rapports", icon: FileBarChart, permission: PERMISSIONS.DOWNLOAD_REPORT },
    ],
  },
  {
    title: "Exploitation",
    items: [
      {
        to: "/maintenances",
        label: "Maintenances",
        icon: CalendarClock,
        permission: PERMISSIONS.VIEW_MAINTENANCE,
      },
      { to: "/interventions", label: "Interventions", icon: Truck, permission: PERMISSIONS.VIEW_INTERVENTIONS },
      {
        to: "/integrations",
        label: "Collecte ETL",
        icon: Plug,
        permission: PERMISSIONS.VIEW_INTEROP,
        badge: "toolsDown",
      },
    ],
  },
  {
    title: "Administration",
    items: [
      {
        to: "/utilisateurs",
        label: "Utilisateurs",
        icon: Users,
        permission: PERMISSIONS.MANAGE_USERS,
      },
      {
        to: "/audit",
        label: "Journal d'audit",
        icon: ScrollText,
        permission: PERMISSIONS.VIEW_AUDIT,
      },
      { to: "/compte", label: "Mon compte", icon: UserCog },
    ],
  },
];

const NAMED_ROUTES = new Set(SECTIONS.flatMap((section) => section.items.map((item) => item.to)));

/**
 * Badge de navigation. Hors « Tout le réseau », il affiche « périmètre /
 * réseau » (INC-09) : un badge 228 à côté d'une page qui montre 0 incident
 * se lisait comme une contradiction. `hot` (rouge plein) est réservé à ce
 * qui exige une action (INC-10).
 */
function NavBadge({ value, scoped, scopeName, label, hot }) {
  if (!value && !scoped) return null;
  const isScoped = scoped !== undefined && scoped !== null;
  return (
    <span
      className="nav-badge num"
      style={hot ? { background: "var(--state-down)" } : undefined}
      title={
        isScoped
          ? `${label} — ${scopeName} : ${scoped} · Tout le réseau : ${value ?? 0}`
          : `${label} — tout le réseau : ${value}`
      }
    >
      {isScoped ? `${scoped} / ${value ?? 0}` : value}
    </span>
  );
}

// Sous 1 024 px (tablette), le rail se replie de lui-même sur ses icônes :
// 208 px de menu sur 800 px d'écran laissaient trop peu aux tableaux.
const NARROW = "(max-width: 1023px)";

function useNarrow() {
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia(NARROW).matches,
  );
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const update = () => setNarrow(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return narrow;
}

/** Carte du logo en tête de la barre latérale (maquette ANPTIC). */
function Brand({ collapsed, to, onNavigate }) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={`brand-card ${collapsed ? "collapsed" : ""}`}
      title="ANPTIC · NOC Supervision — accueil"
    >
      <img src="/images.png" alt="ANPTIC" />
      {!collapsed && (
        <span className="min-w-0">
          <b>NOC · Supervision</b>
          <small>Le label du numérique</small>
        </span>
      )}
    </NavLink>
  );
}

export default function SideNav({
  role,
  toolsDown = 0,
  toolsTotal = 0,
  onNavigate,
  expanded = false,
}) {
  const railCollapsed = useUiStore((s) => s.railCollapsed);
  const narrow = useNarrow();
  // `expanded` : dans le tiroir du téléphone, toujours déplié.
  const collapsed = !expanded && (railCollapsed || narrow);
  // Compteurs de TOUT le réseau : la navigation signale ce qui attend, où
  // que ce soit. Quand un périmètre est choisi, le compteur du périmètre est
  // affiché devant (« 0 / 228 ») pour que le badge et la page concordent.
  const scope = useScopeStore();
  const scopedView = Boolean(scope.region || scope.province || scope.site);
  const { data: overview } = useOverview({ global: true });
  const { data: local } = useOverview();
  const inScope = (pick) => (scopedView && local ? pick(local) ?? 0 : undefined);

  const badges = {
    openIncidents: {
      value: overview?.incidents_total,
      scoped: inScope((o) => o.incidents_total),
      label: "Incidents iTop ouverts",
    },
    // INC-10 : le badge ne montre que ce qui exige une action — les alertes
    // CRITIQUES non acquittées, pas toute la file.
    openAlerts: {
      value: overview?.alerts_critical_unacknowledged,
      scoped: inScope((o) => o.alerts_critical_unacknowledged),
      label: "Alertes critiques non acquittées",
      hot: true,
    },
    nodesDown: {
      value: overview?.nodes_by_state?.down,
      scoped: inScope((o) => o.nodes_by_state?.down),
      label: "Équipements en panne",
      hot: true,
    },
    toolsDown: { value: toolsDown, label: "Outils en erreur", hot: true },
  };

  const home = homeRoute(role);
  const toolsHealthy = Math.max(0, toolsTotal - toolsDown);

  return (
    <nav
      className={`side-nav flex flex-col overflow-y-auto overflow-x-hidden px-2.5 pt-3.5 pb-2 ${
        expanded ? "flex-1" : "shrink-0 h-full"
      }`}
      style={{
        width: expanded ? 272 : collapsed ? "var(--rail-w-collapsed)" : "var(--rail-w)",
        transition: "width .14s ease",
      }}
      aria-label="Navigation principale"
    >
      <Brand collapsed={collapsed} to={home} onNavigate={onNavigate} />

      {SECTIONS.map((section) => {
        // Accueil déjà présent sous son propre nom (Agent-Terrain :
        // Interventions) : une seule entrée, sinon deux sont actives (A19).
        const items = section.items.filter(
          (item) =>
            (!item.permission || hasPermission(role, item.permission)) &&
            !(item.to === "__home__" && NAMED_ROUTES.has(home)),
        );
        if (items.length === 0) return null;

        return (
          <div key={section.title}>
            {!collapsed && <div className="nav-section">{section.title}</div>}
            {collapsed && (
              <div className="mx-2 my-2.5 border-t" style={{ borderColor: "var(--rail-border)" }} />
            )}
            <div className="space-y-1">
              {items.map((item) => {
                const to = item.to === "__home__" ? home : item.to;
                const badge = item.badge ? badges[item.badge] : null;
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={to}
                    end={item.to === "__home__"}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `nav-item ${isActive ? "active" : ""} ${collapsed ? "icon-only" : ""}`
                    }
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon size={19} strokeWidth={1.8} className="shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {!collapsed && badge && (
                      <NavBadge {...badge} scopeName={scopeLabel(scope)} />
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        );
      })}

      {/* Pied de barre : occupe le bas du rail (plus de vide sous le menu)
          et rappelle en permanence ce qui conditionne la fiabilité des
          chiffres — la collecte (INC-32) et le périmètre affiché. */}
      {!collapsed && (
        <div className="rail-foot mt-4">
          {toolsTotal > 0 && (
            <div className="flex items-center gap-2 mb-1">
              <span
                className="dot"
                style={{
                  background:
                    toolsHealthy === 0
                      ? "var(--state-down)"
                      : toolsDown
                        ? "var(--state-degraded)"
                        : "var(--state-up)",
                }}
              />
              <span>
                Collecte <b className="num">{toolsHealthy}/{toolsTotal}</b> sources actives
              </span>
            </div>
          )}
          <div>
            Périmètre : <b>{scopeLabel(scope)}</b>
          </div>
          <div className="mt-1.5" style={{ opacity: 0.8 }}>
            ANPTIC · Centre des opérations réseau
          </div>
        </div>
      )}
    </nav>
  );
}

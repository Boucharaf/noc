import {
  Activity,
  CalendarClock,
  FileBarChart,
  Gauge,
  LayoutDashboard,
  Map,
  Plug,
  Radio,
  Router,
  Truck,
  UserCog,
  Users,
} from "lucide-react";
import { NavLink } from "react-router-dom";

import { PERMISSIONS, hasPermission, homeRoute } from "../../lib/permissions";
import { useAlertSummary, useNodeStates } from "../../hooks/queries";
import { useUiStore } from "../../store/ui";

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
        to: "/incidents",
        label: "Incidents",
        icon: Radio,
        permission: PERMISSIONS.VIEW_INCIDENTS,
        badge: "openIncidents",
      },
      {
        to: "/equipements",
        label: "Équipements",
        icon: Router,
        permission: PERMISSIONS.VIEW_NODES,
        badge: "nodesDown",
      },
      { to: "/carte", label: "Carte des sites", icon: Map, permission: PERMISSIONS.VIEW_MAP },
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
        permission: PERMISSIONS.MANAGE_MAINTENANCE,
      },
      { to: "/terrain", label: "Interventions", icon: Truck, permission: PERMISSIONS.VIEW_TERRAIN },
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
      { to: "/compte", label: "Mon compte", icon: UserCog },
    ],
  },
];

function NavBadge({ value, color }) {
  if (!value) return null;
  return (
    <span
      className="num ml-auto text-[10.5px] px-1 rounded-[3px] font-semibold"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 16%, transparent)`,
      }}
    >
      {value}
    </span>
  );
}

export default function SideNav({ role, toolsDown = 0, onNavigate }) {
  const collapsed = useUiStore((s) => s.railCollapsed);
  const { data: alertSummary } = useAlertSummary();
  const { data: nodeStates } = useNodeStates();

  const badges = {
    openIncidents: { value: alertSummary?.total_open, color: "var(--sev-high)" },
    nodesDown: { value: nodeStates?.down, color: "var(--state-down)" },
    toolsDown: { value: toolsDown, color: "var(--sev-medium)" },
  };

  return (
    <nav
      className="shrink-0 overflow-y-auto overflow-x-hidden border-r py-1"
      style={{
        width: collapsed ? "var(--rail-w-collapsed)" : "var(--rail-w)",
        borderColor: "var(--border)",
        background: "var(--surface)",
        transition: "width .14s ease",
      }}
      aria-label="Navigation principale"
    >
      {SECTIONS.map((section) => {
        const items = section.items.filter(
          (item) => !item.permission || hasPermission(role, item.permission),
        );
        if (items.length === 0) return null;

        return (
          <div key={section.title}>
            {!collapsed && <div className="nav-section">{section.title}</div>}
            {collapsed && (
              <div className="mx-2 my-1.5 border-t" style={{ borderColor: "var(--border)" }} />
            )}
            <div className="px-1.5 space-y-px">
              {items.map((item) => {
                const to = item.to === "__home__" ? homeRoute(role) : item.to;
                const badge = item.badge ? badges[item.badge] : null;
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={to}
                    end={item.to === "__home__"}
                    onClick={onNavigate}
                    className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}
                    title={collapsed ? item.label : undefined}
                  >
                    <Icon size={14} strokeWidth={1.8} className="shrink-0" />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {!collapsed && badge && (
                      <NavBadge value={badge.value} color={badge.color} />
                    )}
                  </NavLink>
                );
              })}
            </div>
          </div>
        );
      })}
    </nav>
  );
}

import React from "react";
import { NavLink } from "react-router-dom";
import {
  Gauge,
  Radar,
  ListChecks,
  Truck,
  Users,
} from "lucide-react";
import { hasPermission, PERMISSIONS } from "../../api/permissions";
import { useAuthStore } from "../../store/auth";

// Grouped by audience, not flattened: a role only ever sees the entry point
// that document defines for it plus what it is explicitly allowed to drill
// into (e.g. Directeur can open the Chef NOC operational view; Chef NOC
// cannot see the Décideur rollup — each dashboard stays scoped to who it was
// built for instead of turning into one shared tab bar again).
export const NAV_ITEMS = [
  { name: "Vue Décideur", path: "/decideur", icon: Gauge, permission: PERMISSIONS.VIEW_DECIDEUR_DASHBOARD },
  { name: "Vue Chef NOC", path: "/chef-noc", icon: Radar, permission: PERMISSIONS.VIEW_CHEF_NOC_DASHBOARD },
  { name: "File d'incidents", path: "/incidents", icon: ListChecks, permission: PERMISSIONS.VIEW_INCIDENT_QUEUE },
  { name: "Mes tournées", path: "/tournees", icon: Truck, permission: PERMISSIONS.VIEW_FIELD_OPS },
];

export const ADMIN_ITEMS = [
  { name: "Utilisateurs", path: "/utilisateurs", icon: Users, permission: PERMISSIONS.MANAGE_USERS },
];

const NavItem = ({ item }) => (
  <NavLink
    to={item.path}
    className={({ isActive }) =>
      `group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors ${
        isActive ? "font-semibold" : "font-medium hover:bg-[var(--color-surface-2)]"
      }`
    }
    style={({ isActive }) => ({
      color: isActive ? "var(--color-text-primary)" : "var(--color-text-secondary)",
      background: isActive ? "var(--color-surface-2)" : "transparent",
      borderLeft: isActive ? "2px solid var(--color-accent)" : "2px solid transparent",
    })}
  >
    <item.icon className="h-4 w-4 shrink-0" />
    <span className="truncate">{item.name}</span>
  </NavLink>
);

const Sidebar = () => {
  const role = useAuthStore((s) => s.user?.role);
  const items = NAV_ITEMS.filter((item) => hasPermission(role, item.permission));
  const adminItems = ADMIN_ITEMS.filter((item) => hasPermission(role, item.permission));

  return (
    <nav
      className="hidden w-52 shrink-0 flex-col gap-0.5 border-r p-2.5 md:flex"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      {items.map((item) => (
        <NavItem key={item.path} item={item} />
      ))}

      {adminItems.length > 0 && (
        <>
          <div
            className="mx-2.5 mb-1 mt-4 border-t pt-3 text-[11px] font-medium"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
          >
            Administration
          </div>
          {adminItems.map((item) => (
            <NavItem key={item.path} item={item} />
          ))}
        </>
      )}
    </nav>
  );
};

export default Sidebar;

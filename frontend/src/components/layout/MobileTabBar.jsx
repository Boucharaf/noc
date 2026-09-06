import React from "react";
import { NavLink } from "react-router-dom";
import { hasPermission } from "../../api/permissions";
import { useAuthStore } from "../../store/auth";
import { NAV_ITEMS, ADMIN_ITEMS } from "./Sidebar";

const MobileTabBar = () => {
  const role = useAuthStore((s) => s.user?.role);
  const items = [...NAV_ITEMS, ...ADMIN_ITEMS].filter((item) =>
    hasPermission(role, item.permission)
  );

  if (items.length <= 1) return null;

  return (
    <nav
      className="flex shrink-0 items-stretch border-t md:hidden"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      {items.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium"
          style={({ isActive }) => ({
            color: isActive ? "var(--color-accent)" : "var(--color-text-secondary)",
          })}
        >
          <item.icon className="h-[18px] w-[18px]" />
          <span className="truncate px-1">{item.name}</span>
        </NavLink>
      ))}
    </nav>
  );
};

export default MobileTabBar;

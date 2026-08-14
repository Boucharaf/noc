import React from 'react';
import { NavLink } from 'react-router-dom';
import { Globe, Map, MapPin, ShieldAlert, Zap, Database } from 'lucide-react';

const TabNav = () => {
  const tabs = [
    { name: 'Vue Globale', path: '/global', icon: Globe },
    { name: 'Vue par Localité', path: '/locality', icon: MapPin },
    { name: 'Carte', path: '/map', icon: Map },
    { name: 'SLA & Alertes', path: '/sla', icon: ShieldAlert },
    { name: 'Interopérabilité', path: '/interop', icon: Zap },
    { name: 'Modèle de Données', path: '/datamodel', icon: Database },
  ];

  return (
    <nav
      className="sticky top-[57px] z-10 flex gap-1 overflow-x-auto border-b px-3 md:px-6"
      style={{ background: 'var(--color-surface)', borderColor: 'var(--color-border)' }}
    >
      {tabs.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          className={({ isActive }) =>
            `relative flex shrink-0 items-center gap-2 whitespace-nowrap px-3 py-3 text-sm font-medium transition-colors ${
              isActive ? '' : 'hover:text-[var(--color-text-primary)]'
            }`
          }
          style={({ isActive }) => ({
            color: isActive ? 'var(--color-accent)' : 'var(--color-text-secondary)',
          })}
        >
          {({ isActive }) => (
            <>
              <tab.icon className="h-4 w-4" />
              {tab.name}
              <span
                className="absolute inset-x-1 -bottom-px h-0.5 rounded-full transition-opacity"
                style={{ background: 'var(--color-accent)', opacity: isActive ? 1 : 0 }}
              />
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
};

export default TabNav;

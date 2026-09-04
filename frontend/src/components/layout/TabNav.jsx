import React from 'react';
import { NavLink } from 'react-router-dom';
import { Globe, ListChecks, Map, MapPin, ShieldAlert, Truck, Zap, Database } from 'lucide-react';
import { hasPermission, PERMISSIONS } from '../../api/permissions';
import { useAuthStore } from '../../store/auth';

const ALL_TABS = [
  { name: 'Vue Globale', path: '/global', icon: Globe, permission: PERMISSIONS.VIEW_KPI_GLOBAL },
  { name: 'Vue par Localité', path: '/locality', icon: MapPin, permission: PERMISSIONS.VIEW_KPI_LOCALITY },
  { name: 'Carte', path: '/map', icon: Map, permission: PERMISSIONS.VIEW_KPI_LOCALITY },
  { name: 'SLA & Alertes', path: '/sla', icon: ShieldAlert, permission: PERMISSIONS.VIEW_SLA },
  { name: 'Interopérabilité', path: '/interop', icon: Zap, permission: PERMISSIONS.VIEW_INTEROP_STATUS },
  { name: 'Modèle de Données', path: '/datamodel', icon: Database, permission: PERMISSIONS.VIEW_DATA_MODEL },
  { name: 'Mes Alertes', path: '/mes-alertes', icon: ListChecks, permission: PERMISSIONS.VIEW_ALERTS },
  { name: 'Mes Tournées', path: '/mes-tournees', icon: Truck, permission: PERMISSIONS.MANAGE_FIELD_INTERVENTIONS },
];

const TabNav = () => {
  // Un onglet n'est affiché que si le rôle connecté a la permission
  // correspondante — auparavant tous les onglets étaient visibles à tout le
  // monde, y compris ceux menant à un écran auquel le rôle n'a pas accès.
  // hasPermission() (fonction pure) plutôt que useHasPermission() (hook) ici
  // : un hook ne doit pas être appelé dans un callback .filter().
  const role = useAuthStore((s) => s.user?.role);
  const tabs = ALL_TABS.filter((tab) => hasPermission(role, tab.permission));

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

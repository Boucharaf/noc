import { useAuthStore } from "../store/auth";
import { hasPermission } from "../api/permissions";

// Usage : const canResolve = useHasPermission(PERMISSIONS.RESOLVE_INCIDENT);
// À utiliser pour masquer/désactiver un bouton — le vrai filet de sécurité
// reste le 403 backend + assertPermission() côté api/*.js (voir permissions.js).
export const useHasPermission = (permission) =>
  useAuthStore((state) => hasPermission(state.user?.role, permission));

// Pour les gardes conditionnelles dans le JSX : <Guard permission={...}>...</Guard>
export const useRole = () => useAuthStore((state) => state.user?.role);
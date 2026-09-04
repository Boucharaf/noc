import React from "react";
import { Navigate } from "react-router-dom";
import { useHasPermission } from "../hooks/usePermission";
import { getHomeRoute } from "../utils/roleHome";
import { useAuthStore } from "../store/auth";

// Défense en profondeur côté route, comme api/permissions.js l'est côté
// appel API : un rôle qui n'a pas la permission ne voit même pas
// l'écran (au lieu de le voir puis se cogner à des cartes vides / 403 en
// boucle). Le vrai filet de sécurité reste le 403 backend.
const RequirePermission = ({ permission, children }) => {
  const allowed = useHasPermission(permission);
  const role = useAuthStore((s) => s.user?.role);

  if (!allowed) {
    return <Navigate to={getHomeRoute(role)} replace />;
  }
  return children;
};

export default RequirePermission;

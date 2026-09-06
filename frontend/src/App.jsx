import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import RequirePermission from "./components/RequirePermission";
import DecideurView from "./pages/DecideurView";
import ChefNocView from "./pages/ChefNocView";
import IncidentQueueView from "./pages/IncidentQueueView";
import FieldOpsView from "./pages/FieldOpsView";
import UsersAdminView from "./pages/UsersAdminView";
import Login from "./pages/Login";
import { useAuthStore } from "./store/auth";
import { usePeriodAutoSync } from "./hooks/usePeriodAutoSync";
import { useSessionKeepAlive } from "./hooks/useSessionKeepAlive";
import { PERMISSIONS } from "./api/permissions";
import { getHomeRoute } from "./utils/roleHome";

// Un tableau de bord par profil (voir l'architecture à 4 niveaux du document
// métier) plutôt qu'une liste d'onglets génériques filtrés par permission :
// chaque route est l'écran d'accueil complet d'un rôle, pas un fragment
// partagé. RequirePermission reste la défense en profondeur habituelle —
// le vrai filet de sécurité est le 403 renvoyé par chaque endpoint backend.
const DashboardShell = () => {
  const token = useAuthStore((s) => s.token);
  const role = useAuthStore((s) => s.user?.role);
  usePeriodAutoSync();
  useSessionKeepAlive();

  if (!token) return <Navigate to="/login" replace />;

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to={getHomeRoute(role)} replace />} />
        <Route
          path="/decideur"
          element={
            <RequirePermission permission={PERMISSIONS.VIEW_DECIDEUR_DASHBOARD}>
              <DecideurView />
            </RequirePermission>
          }
        />
        <Route
          path="/chef-noc"
          element={
            <RequirePermission permission={PERMISSIONS.VIEW_CHEF_NOC_DASHBOARD}>
              <ChefNocView />
            </RequirePermission>
          }
        />
        <Route
          path="/incidents"
          element={
            <RequirePermission permission={PERMISSIONS.VIEW_INCIDENT_QUEUE}>
              <IncidentQueueView />
            </RequirePermission>
          }
        />
        <Route
          path="/tournees"
          element={
            <RequirePermission permission={PERMISSIONS.VIEW_FIELD_OPS}>
              <FieldOpsView />
            </RequirePermission>
          }
        />
        <Route
          path="/utilisateurs"
          element={
            <RequirePermission permission={PERMISSIONS.MANAGE_USERS}>
              <UsersAdminView />
            </RequirePermission>
          }
        />
        <Route path="*" element={<Navigate to={getHomeRoute(role)} replace />} />
      </Routes>
    </AppShell>
  );
};

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/*" element={<DashboardShell />} />
      </Routes>
    </Router>
  );
}

export default App;

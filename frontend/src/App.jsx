import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import Header from "./components/layout/Header";
import TabNav from "./components/layout/TabNav";
import RequirePermission from "./components/RequirePermission";
import GlobalView from "./pages/GlobalView";
import LocalityView from "./pages/LocalityView";
import MapView from "./pages/MapView";
import SLAView from "./pages/SLAView";
import InteropView from "./pages/InteropView";
import DataModelView from "./pages/DataModelView";
import TechnicienQueueView from "./pages/TechnicienQueueView";
import AgentTerrainView from "./pages/AgentTerrainView";
import Login from "./pages/Login";
import { useAuthStore } from "./store/auth";
import { usePeriodAutoSync } from "./hooks/usePeriodAutoSync";
import { useSessionKeepAlive } from "./hooks/useSessionKeepAlive";
import { PERMISSIONS } from "./api/permissions";
import { getHomeRoute } from "./utils/roleHome";

const DashboardShell = () => {
  const token = useAuthStore((s) => s.token);
  const role = useAuthStore((s) => s.user?.role);
  usePeriodAutoSync();
  useSessionKeepAlive();

  if (!token) return <Navigate to="/login" replace />;

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-[var(--color-page)] text-[var(--color-text-primary)]">
      <Header />
      <TabNav />
      <main className="flex flex-1 min-h-0 flex-col overflow-y-auto p-4 md:p-6 w-full">
        <Routes>
          <Route path="/" element={<Navigate to={getHomeRoute(role)} replace />} />
          <Route
            path="/global"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_KPI_GLOBAL}>
                <GlobalView />
              </RequirePermission>
            }
          />
          <Route
            path="/locality"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_KPI_LOCALITY}>
                <LocalityView />
              </RequirePermission>
            }
          />
          <Route
            path="/map"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_KPI_LOCALITY}>
                <MapView />
              </RequirePermission>
            }
          />
          <Route
            path="/sla"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_SLA}>
                <SLAView />
              </RequirePermission>
            }
          />
          <Route
            path="/interop"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_INTEROP_STATUS}>
                <InteropView />
              </RequirePermission>
            }
          />
          <Route
            path="/datamodel"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_DATA_MODEL}>
                <DataModelView />
              </RequirePermission>
            }
          />
          <Route
            path="/mes-alertes"
            element={
              <RequirePermission permission={PERMISSIONS.VIEW_ALERTS}>
                <TechnicienQueueView />
              </RequirePermission>
            }
          />
          <Route
            path="/mes-tournees"
            element={
              <RequirePermission permission={PERMISSIONS.MANAGE_FIELD_INTERVENTIONS}>
                <AgentTerrainView />
              </RequirePermission>
            }
          />
        </Routes>
      </main>
    </div>
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

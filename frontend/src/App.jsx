import React from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import Header from "./components/layout/Header";
import TabNav from "./components/layout/TabNav";
import GlobalView from "./pages/GlobalView";
import LocalityView from "./pages/LocalityView";
import SLAView from "./pages/SLAView";
import InteropView from "./pages/InteropView";
import DataModelView from "./pages/DataModelView";
import Login from "./pages/Login";
import { useAuthStore } from "./store/auth";
import { usePeriodAutoSync } from "./hooks/usePeriodAutoSync";

const DashboardShell = () => {
  const token = useAuthStore((s) => s.token);
  usePeriodAutoSync();

  if (!token) return <Navigate to="/login" replace />;

  return (
    <div className="h-screen overflow-hidden flex flex-col bg-[var(--color-page)] text-[var(--color-text-primary)]">
      <Header />
      <TabNav />
      <main className="flex flex-1 min-h-0 flex-col overflow-y-auto p-4 md:p-6 w-full">
        <Routes>
          <Route path="/" element={<Navigate to="/global" replace />} />
          <Route path="/global" element={<GlobalView />} />
          <Route path="/locality" element={<LocalityView />} />
          <Route path="/sla" element={<SLAView />} />
          <Route path="/interop" element={<InteropView />} />
          <Route path="/datamodel" element={<DataModelView />} />
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

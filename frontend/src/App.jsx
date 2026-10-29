import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/layout/AppShell";
import ForbiddenPage from "./pages/ForbiddenPage";
import LoginPage from "./pages/LoginPage";
import { LoadingState } from "./components/ui/States";
import { PERMISSIONS, hasPermission, homeRoute } from "./lib/permissions";
import { useAuthStore } from "./store/auth";
import {
  usePeriodAutoSync,
  useSessionBootstrap,
  useSessionKeepAlive,
  useThemeEffect,
} from "./hooks/useSession";

/**
 * Routage.
 *
 * Structure en deux niveaux, qui traduit directement l'architecture
 * métier à quatre niveaux :
 *
 *   · un ÉCRAN D'ACCUEIL par profil (/direction, /supervision, /console,
 *     /terrain) — c'est l'écran complet du rôle, pas un onglet ;
 *   · des écrans TRANSVERSES de drill-down, partagés mais protégés par
 *     permission (incidents, équipements, carte, SLA, collecte…).
 *
 * Chaque écran transverse est atteignable depuis plusieurs points
 * d'entrée : c'est ce qui rend le parcours « KPI global → ministère →
 * site → équipement → incident » possible dans les deux sens.
 *
 * Le chargement différé (`lazy`) n'est pas de l'optimisation gratuite :
 * Leaflet et Chart.js pèsent lourd, et l'agent terrain sur téléphone en
 * 3G ne doit pas les télécharger pour consulter sa tournée.
 */

const DirectionView = lazy(() => import("./pages/DirectionView"));
const SupervisionView = lazy(() => import("./pages/SupervisionView"));
const ConsoleView = lazy(() => import("./pages/ConsoleView"));
const InterventionsPage = lazy(() => import("./pages/InterventionsPage"));
const IncidentsPage = lazy(() => import("./pages/IncidentsPage"));
const AlertsPage = lazy(() => import("./pages/AlertsPage"));
const TerritoryPage = lazy(() => import("./pages/TerritoryPage"));
const NodesPage = lazy(() => import("./pages/NodesPage"));
const NodeDetailPage = lazy(() => import("./pages/NodeDetailPage"));
const PerformancePage = lazy(() => import("./pages/PerformancePage"));
const SlaPage = lazy(() => import("./pages/SlaPage"));
const IntegrationsPage = lazy(() => import("./pages/IntegrationsPage"));
const MaintenancePage = lazy(() => import("./pages/MaintenancePage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const UsersPage = lazy(() => import("./pages/UsersPage"));
const AuditPage = lazy(() => import("./pages/AuditPage"));
const AccountPage = lazy(() => import("./pages/AccountPage"));
const WallboardPage = lazy(() => import("./pages/WallboardPage"));

/**
 * Garde de permission.
 *
 * Défense en profondeur : le vrai contrôle est le 403 renvoyé par chaque
 * endpoint. Cette garde évite seulement d'afficher un écran dont toutes
 * les requêtes échoueraient — et de faire croire à une panne.
 */
function Guard({ permission, children }) {
  const role = useAuthStore((s) => s.user?.role);
  if (!hasPermission(role, permission)) return <ForbiddenPage />;
  return children;
}

function Protected({ children }) {
  const token = useAuthStore((s) => s.token);
  const bootstrapped = useAuthStore((s) => s.bootstrapped);

  // Tant que la restauration de session n'a pas abouti, on ne peut pas
  // savoir si l'utilisateur est connecté : rediriger tout de suite vers
  // la page de connexion la ferait clignoter à chaque rechargement.
  if (!bootstrapped) {
    return (
      <div className="h-full flex items-center justify-center">
        <LoadingState label="Restauration de la session…" />
      </div>
    );
  }
  if (!token) return <Navigate to="/connexion" replace />;
  return children;
}

function RoleHome() {
  const role = useAuthStore((s) => s.user?.role);
  return <Navigate to={homeRoute(role)} replace />;
}

export default function App() {
  useSessionBootstrap();
  useSessionKeepAlive();
  usePeriodAutoSync();
  useThemeEffect();

  return (
    <BrowserRouter>
      <Suspense
        fallback={
          <div className="h-full flex items-center justify-center">
            <LoadingState />
          </div>
        }
      >
        <Routes>
          <Route path="/connexion" element={<LoginPage />} />

          {/* Mur d'écrans : hors de la coque, il occupe tout l'écran. */}
          <Route
            path="/mur"
            element={
              <Protected>
                <WallboardPage />
              </Protected>
            }
          />

          <Route
            element={
              <Protected>
                <AppShell />
              </Protected>
            }
          >
            <Route path="/" element={<RoleHome />} />

            {/* --- Écrans d'accueil par profil --- */}
            <Route
              path="/direction"
              element={
                <Guard permission={PERMISSIONS.VIEW_DIRECTION}>
                  <DirectionView />
                </Guard>
              }
            />
            <Route
              path="/supervision"
              element={
                <Guard permission={PERMISSIONS.VIEW_SUPERVISION}>
                  <SupervisionView />
                </Guard>
              }
            />
            <Route
              path="/console"
              element={
                <Guard permission={PERMISSIONS.VIEW_CONSOLE}>
                  <ConsoleView />
                </Guard>
              }
            />
            <Route
              path="/interventions"
              element={
                <Guard permission={PERMISSIONS.VIEW_INTERVENTIONS}>
                  <InterventionsPage />
                </Guard>
              }
            />
            {/* Ancienne application Terrain : les interventions sont désormais
                les ordres de travail iTop. Les liens enregistrés suivent. */}
            <Route path="/terrain" element={<Navigate to="/interventions" replace />} />

            {/* --- Écrans transverses --- */}
            <Route
              path="/incidents"
              element={
                <Guard permission={PERMISSIONS.VIEW_INCIDENTS}>
                  <IncidentsPage />
                </Guard>
              }
            />
            <Route
              path="/alertes"
              element={
                <Guard permission={PERMISSIONS.VIEW_ALERTS}>
                  <AlertsPage />
                </Guard>
              }
            />
            <Route
              path="/territoire"
              element={
                <Guard permission={PERMISSIONS.VIEW_MAP}>
                  <TerritoryPage />
                </Guard>
              }
            />
            <Route
              path="/equipements"
              element={
                <Guard permission={PERMISSIONS.VIEW_NODES}>
                  <NodesPage />
                </Guard>
              }
            />
            <Route
              path="/equipements/:nodeId"
              element={
                <Guard permission={PERMISSIONS.VIEW_NODES}>
                  <NodeDetailPage />
                </Guard>
              }
            />
            {/* Ancienne « Carte des sites » : remplacée par Territoire. */}
            <Route path="/carte" element={<Navigate to="/territoire" replace />} />
            <Route
              path="/performance"
              element={
                <Guard permission={PERMISSIONS.VIEW_METRICS}>
                  <PerformancePage />
                </Guard>
              }
            />
            <Route
              path="/sla"
              element={
                <Guard permission={PERMISSIONS.VIEW_SLA}>
                  <SlaPage />
                </Guard>
              }
            />
            <Route
              path="/integrations"
              element={
                <Guard permission={PERMISSIONS.VIEW_INTEROP}>
                  <IntegrationsPage />
                </Guard>
              }
            />
            <Route
              path="/maintenances"
              element={
                <Guard permission={PERMISSIONS.VIEW_MAINTENANCE}>
                  <MaintenancePage />
                </Guard>
              }
            />
            <Route
              path="/rapports"
              element={
                <Guard permission={PERMISSIONS.DOWNLOAD_REPORT}>
                  <ReportsPage />
                </Guard>
              }
            />
            <Route
              path="/utilisateurs"
              element={
                <Guard permission={PERMISSIONS.MANAGE_USERS}>
                  <UsersPage />
                </Guard>
              }
            />
            <Route
              path="/audit"
              element={
                <Guard permission={PERMISSIONS.VIEW_AUDIT}>
                  <AuditPage />
                </Guard>
              }
            />
            <Route path="/compte" element={<AccountPage />} />

            {/* Toute URL inconnue ramène à l'accueil du rôle plutôt qu'à
                une page d'erreur : sur un poste de supervision, un lien
                obsolète ne doit jamais laisser l'écran vide. */}
            <Route path="*" element={<RoleHome />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

import React, { useState } from "react";
import {
  Bell,
  BellOff,
  BellRing,
  ChevronLeft,
  ChevronRight,
  FileDown,
  LogOut,
  Moon,
  Sun,
} from "lucide-react";
import { usePeriodStore } from "../../store";
import { useThemeStore } from "../../store/theme";
import { useAuthStore } from "../../store/auth";
import { useClock } from "../../hooks/useClock";
import { usePushNotifications } from "../../hooks/usePushNotifications";
import { downloadMonthlyReport } from "../../api/report";
import logo from "../../assets/images/noc-logo-256.png";

const MONTH_LABELS = [
  "Janvier",
  "Février",
  "Mars",
  "Avril",
  "Mai",
  "Juin",
  "Juillet",
  "Août",
  "Septembre",
  "Octobre",
  "Novembre",
  "Décembre",
];

// Compact labels so the period selector fits on phone-width headers
const MONTH_LABELS_SHORT = [
  "Janv.",
  "Févr.",
  "Mars",
  "Avr.",
  "Mai",
  "Juin",
  "Juil.",
  "Août",
  "Sept.",
  "Oct.",
  "Nov.",
  "Déc.",
];

const ROLE_LABEL = {
  admin: "Administrateur",
  analyst: "Analyste",
  noc_agent: "Agent NOC",
};

const initials = (name = "") =>
  name
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

const Header = () => {
  const { month, year, goToPreviousMonth, goToNextMonth } = usePeriodStore();
  const { theme, toggleTheme } = useThemeStore();
  const { user, logout } = useAuthStore();
  const push = usePushNotifications();
  const [menuOpen, setMenuOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const now = useClock();

  const exportReport = async (format) => {
    setExportOpen(false);
    setExporting(true);
    try {
      await downloadMonthlyReport(month, year, format);
    } catch (error) {
      console.error("Export du rapport échoué:", error);
    } finally {
      setExporting(false);
    }
  };

  const timeLabel = now.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const dateLabel = now.toLocaleDateString("fr-FR", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });

  return (
    <header
      className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b px-4 py-3 md:px-6"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
        boxShadow: "var(--shadow-elevate)",
      }}
    >
      <div className="flex items-center gap-3">
        <div className="relative h-9 w-9 shrink-0">
          <img src={logo} alt="NOC" className="h-9 w-9 rounded-lg" />
          {/* <span className="absolute -right-1 -top-1 flex h-3 w-3">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-3 w-3 rounded-full bg-emerald-500 ring-2 ring-[var(--color-surface)]" />
          </span> */}
        </div>
        <div className="hidden leading-tight min-[420px]:block">
          <h1 className="text-base font-bold tracking-tight md:text-lg">NOC</h1>
          <p
            className="hidden text-xs sm:block"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Centre des Opérations Réseau
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2 md:gap-4">
        <div
          className="hidden items-center gap-2 rounded-lg border px-3 py-1.5 font-mono text-xs lg:flex"
          style={{
            borderColor: "var(--color-border)",
            color: "var(--color-text-secondary)",
          }}
        >
          <span className="capitalize">{dateLabel}</span>
          <span
            className="h-3 w-px"
            style={{ background: "var(--color-border-strong)" }}
          />
          <span
            className="tabular-nums"
            style={{ color: "var(--color-text-primary)" }}
          >
            {timeLabel}
          </span>
        </div>

        <div
          className="flex items-center rounded-lg border px-1 py-1"
          style={{ borderColor: "var(--color-border)" }}
        >
          <button
            onClick={goToPreviousMonth}
            className="rounded-md p-1.5 transition-colors hover:bg-[var(--color-surface-2)]"
            aria-label="Mois précédent"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="w-20 text-center text-xs font-semibold sm:w-32 sm:text-sm">
            <span className="sm:hidden">
              {MONTH_LABELS_SHORT[month - 1]} {year}
            </span>
            <span className="hidden sm:inline">
              {MONTH_LABELS[month - 1]} {year}
            </span>
          </span>
          <button
            onClick={goToNextMonth}
            className="rounded-md p-1.5 transition-colors hover:bg-[var(--color-surface-2)]"
            aria-label="Mois suivant"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="relative">
          <button
            onClick={() => setExportOpen((v) => !v)}
            disabled={exporting}
            className="rounded-lg border p-2 transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
            style={{ borderColor: "var(--color-border)" }}
            aria-label="Exporter le rapport mensuel"
            title="Exporter le rapport mensuel"
          >
            <FileDown className="h-4 w-4" />
          </button>
          {exportOpen && (
            <>
              <div
                className="fixed inset-0 z-30"
                onClick={() => setExportOpen(false)}
              />
              <div
                className="absolute right-0 z-40 mt-2 w-44 rounded-lg border p-2 text-sm"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-border-strong)",
                  boxShadow: "var(--shadow-elevate)",
                }}
              >
                <p
                  className="px-2 py-1 text-xs font-semibold uppercase tracking-wide"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  Rapport {MONTH_LABELS[month - 1]} {year}
                </p>
                <button
                  onClick={() => exportReport("pdf")}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                >
                  <FileDown className="h-4 w-4" />
                  Export PDF
                </button>
                <button
                  onClick={() => exportReport("docx")}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                >
                  <FileDown className="h-4 w-4" />
                  Export DOCX
                </button>
              </div>
            </>
          )}
        </div>

        {push.supported && (
          <button
            onClick={push.toggle}
            disabled={push.loading || push.permission === "denied"}
            className="rounded-lg border p-2 transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
            style={{
              borderColor: push.error ? "var(--color-critical, #d03b3b)" : "var(--color-border)",
              color: push.error
                ? "var(--color-critical, #d03b3b)"
                : push.subscribed
                  ? "var(--color-accent)"
                  : undefined,
            }}
            aria-label="Notifications push"
            title={
              push.error
                ? `Échec de l'activation : ${push.error}`
                : push.permission === "denied"
                  ? "Notifications bloquées — autorisez-les dans les réglages du navigateur"
                  : push.subscribed
                    ? "Désactiver les notifications push"
                    : "Activer les notifications push pour les incidents critiques"
            }
          >
            {push.permission === "denied" ? (
              <BellOff className="h-4 w-4" />
            ) : push.subscribed ? (
              <BellRing className="h-4 w-4" />
            ) : (
              <Bell className="h-4 w-4" />
            )}
          </button>
        )}

        <button
          onClick={toggleTheme}
          className="rounded-lg border p-2 transition-colors hover:bg-[var(--color-surface-2)]"
          style={{ borderColor: "var(--color-border)" }}
          aria-label="Changer de thème"
          title={
            theme === "dark" ? "Passer en mode clair" : "Passer en mode sombre"
          }
        >
          {theme === "dark" ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
        </button>

        <div className="relative">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-[var(--color-accent-soft)] text-xs font-bold text-[var(--color-accent)]"
            aria-label="Menu utilisateur"
          >
            {initials(user?.full_name) || "?"}
          </button>
          {menuOpen && (
            <>
              <div
                className="fixed inset-0 z-30"
                onClick={() => setMenuOpen(false)}
              />
              <div
                className="absolute right-0 z-40 mt-2 w-52 rounded-lg border p-2 text-sm"
                style={{
                  background: "var(--color-surface)",
                  borderColor: "var(--color-border-strong)",
                  boxShadow: "var(--shadow-elevate)",
                }}
              >
                <div className="px-2 py-1.5">
                  <p
                    className="font-semibold"
                    style={{ color: "var(--color-text-primary)" }}
                  >
                    {user?.full_name}
                  </p>
                  <p
                    className="text-xs"
                    style={{ color: "var(--color-text-secondary)" }}
                  >
                    {ROLE_LABEL[user?.role] ?? user?.role}
                  </p>
                </div>
                <button
                  onClick={logout}
                  className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  <LogOut className="h-4 w-4" />
                  Se déconnecter
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
};

export default Header;

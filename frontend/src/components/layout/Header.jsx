import React, { useState } from "react";
import {
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
import { useHasPermission } from "../../hooks/usePermission";
import { downloadMonthlyReport } from "../../api/report";
import { PERMISSIONS } from "../../api/permissions";
import NotificationsBell from "../NotificationsBell";
import Logo from "../Logo";

const MONTH_LABELS = [
  "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
  "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
];

const MONTH_LABELS_SHORT = [
  "Janv.", "Févr.", "Mars", "Avr.", "Mai", "Juin",
  "Juil.", "Août", "Sept.", "Oct.", "Nov.", "Déc.",
];

export const ROLE_LABEL = {
  directeur: "Directeur",
  chef_noc: "Chef NOC",
  technicien: "Technicien / Ingénieur",
  agent_terrain: "Agent terrain",
};

const initials = (name = "") =>
  name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase();

/**
 * Top strip only — navigation lives in the Sidebar, not here. The period
 * picker and report export are hidden for roles the period concept doesn't
 * apply to (agent_terrain works a live queue, not a monthly rollup) or that
 * the backend does not grant (report is directeur/chef_noc only server-side —
 * see app/routes/report.py — this just avoids an unusable button, the 403
 * stays the real guard).
 */
const Header = () => {
  const { month, year, goToPreviousMonth, goToNextMonth } = usePeriodStore();
  const { theme, toggleTheme } = useThemeStore();
  const { user, logout } = useAuthStore();
  const [menuOpen, setMenuOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const now = useClock();
  const canDownloadReport = useHasPermission(PERMISSIONS.DOWNLOAD_REPORT);
  const showPeriodPicker = user?.role !== "agent_terrain";

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
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
  const dateLabel = now.toLocaleDateString("fr-FR", {
    weekday: "short", day: "2-digit", month: "short",
  });

  return (
    <header
      className="flex h-14 shrink-0 items-center justify-between gap-4 border-b px-4 md:px-5"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      <div className="flex items-center gap-2.5">
        <Logo size={30} />
        <div className="hidden leading-tight min-[420px]:block">
          <h1 className="text-sm font-bold tracking-tight">RESINA · NOC</h1>
          <p className="hidden text-[11px] sm:block" style={{ color: "var(--color-text-secondary)" }}>
            Centre des Opérations Réseau
          </p>
        </div>
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2 md:gap-3">
        <div
          className="hidden items-center gap-2 rounded-md border px-2.5 py-1.5 lg:flex"
          style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)" }}
        >
          <span className="capitalize text-xs">{dateLabel}</span>
          <span className="h-3 w-px" style={{ background: "var(--color-border-strong)" }} />
          <span className="text-xs tabular-nums" style={{ color: "var(--color-text-primary)" }}>
            {timeLabel}
          </span>
          <span className="noc-live-dot" title="Horloge en direct" />
        </div>

        {showPeriodPicker && (
          <div className="flex items-center rounded-md border px-1 py-1" style={{ borderColor: "var(--color-border)" }}>
            <button
              onClick={goToPreviousMonth}
              className="rounded p-1.5 transition-colors hover:bg-[var(--color-surface-2)]"
              aria-label="Mois précédent"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="w-20 text-center text-xs font-semibold sm:w-28">
              <span className="sm:hidden">{MONTH_LABELS_SHORT[month - 1]} {year}</span>
              <span className="hidden sm:inline">{MONTH_LABELS[month - 1]} {year}</span>
            </span>
            <button
              onClick={goToNextMonth}
              className="rounded p-1.5 transition-colors hover:bg-[var(--color-surface-2)]"
              aria-label="Mois suivant"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        )}

        {canDownloadReport && (
          <div className="relative">
            <button
              onClick={() => setExportOpen((v) => !v)}
              disabled={exporting}
              className="rounded-md border p-2 transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
              style={{ borderColor: "var(--color-border)" }}
              aria-label="Exporter le rapport mensuel"
              title="Exporter le rapport mensuel"
            >
              <FileDown className="h-4 w-4" />
            </button>
            {exportOpen && (
              <>
                <div className="fixed inset-0 z-30" onClick={() => setExportOpen(false)} />
                <div
                  className="absolute right-0 z-40 mt-2 w-44 rounded-lg border p-2 text-sm"
                  style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}
                >
                  <p className="px-2 py-1 text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>
                    Rapport {MONTH_LABELS[month - 1]} {year}
                  </p>
                  <button
                    onClick={() => exportReport("pdf")}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                  >
                    <FileDown className="h-4 w-4" /> Export PDF
                  </button>
                  <button
                    onClick={() => exportReport("docx")}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                  >
                    <FileDown className="h-4 w-4" /> Export DOCX
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        <NotificationsBell />

        <button
          onClick={toggleTheme}
          className="rounded-md border p-2 transition-colors hover:bg-[var(--color-surface-2)]"
          style={{ borderColor: "var(--color-border)" }}
          aria-label="Changer de thème"
          title={theme === "dark" ? "Passer en mode clair" : "Passer en mode sombre"}
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
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
              <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
              <div
                className="absolute right-0 z-40 mt-2 w-52 rounded-lg border p-2 text-sm"
                style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}
              >
                <div className="px-2 py-1.5">
                  <p className="font-semibold" style={{ color: "var(--color-text-primary)" }}>{user?.full_name}</p>
                  <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
                    {ROLE_LABEL[user?.role] ?? user?.role}
                  </p>
                </div>
                <button
                  onClick={logout}
                  className="mt-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--color-surface-2)]"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  <LogOut className="h-4 w-4" /> Se déconnecter
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

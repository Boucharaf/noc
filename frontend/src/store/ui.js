import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Préférences d'affichage et période de consultation.
 *
 * Persistées (localStorage) parce qu'un poste de supervision est
 * personnel : rebasculer en thème clair et replier la navigation à chaque
 * rechargement est une friction quotidienne. La PÉRIODE, elle, n'est PAS
 * persistée — rouvrir le dashboard trois semaines plus tard sur « mars »
 * parce qu'on l'avait consulté une fois serait un piège.
 */

const currentPeriod = () => {
  const now = new Date();
  return { month: now.getMonth() + 1, year: now.getFullYear() };
};

const isCurrent = (month, year) => {
  const now = currentPeriod();
  return month === now.month && year === now.year;
};

export const useUiStore = create(
  persist(
    (set) => ({
      theme: "dark", // le NOC tourne en salle sombre : c'est le défaut
      railCollapsed: false,
      // Rafraîchissement automatique des vues temps réel. Coupable : sur
      // une liaison satellite de secours, un poll toutes les 15 s coûte
      // plus que ce qu'il rapporte.
      autoRefresh: true,

      toggleTheme: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setTheme: (theme) => set({ theme }),
      toggleRail: () => set((s) => ({ railCollapsed: !s.railCollapsed })),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
    }),
    {
      name: "noc-ui",
      partialize: (s) => ({
        theme: s.theme,
        railCollapsed: s.railCollapsed,
        autoRefresh: s.autoRefresh,
      }),
    },
  ),
);

export const usePeriodStore = create((set, get) => ({
  ...currentPeriod(),
  // Le dashboard reste ouvert des semaines sur un écran de salle : la
  // période ne peut pas être lue une fois au chargement, elle doit
  // basculer d'elle-même au changement de mois. Sauf si quelqu'un
  // consulte un mois passé — d'où ce drapeau, posé dès qu'un mois est
  // choisi à la main et levé quand on revient sur le mois courant.
  pinned: false,

  setPeriod: (month, year) => set({ month, year, pinned: !isCurrent(month, year) }),

  previousMonth: () => {
    const { month, year, setPeriod } = get();
    if (month === 1) setPeriod(12, year - 1);
    else setPeriod(month - 1, year);
  },

  nextMonth: () => {
    const { month, year, setPeriod } = get();
    const now = currentPeriod();
    // Interdit d'aller au-delà du mois courant : un mois futur ne
    // renverrait que des zéros, ce qui se lit comme une panne.
    if (month === now.month && year === now.year) return;
    if (month === 12) setPeriod(1, year + 1);
    else setPeriod(month + 1, year);
  },

  goToCurrent: () => set({ ...currentPeriod(), pinned: false }),

  syncToCurrent: () => {
    const { month, year, pinned } = get();
    if (pinned) return;
    const now = currentPeriod();
    if (now.month !== month || now.year !== year) set(now);
  },

  isCurrentPeriod: () => {
    const { month, year } = get();
    return isCurrent(month, year);
  },
}));

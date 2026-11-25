import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

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
      // Clair par défaut, aux couleurs ANPTIC (AM-01) ; le mode sombre reste
      // à un clic pour la salle NOC (bouton de l'en-tête, mur d'écrans).
      theme: "light",
      railCollapsed: false,
      // Rafraîchissement automatique des vues temps réel. Coupable : sur
      // une liaison satellite de secours, un poll toutes les 15 s coûte
      // plus que ce qu'il rapporte.
      autoRefresh: true,
      // Taille d'affichage : « auto » agrandit l'interface sur les très
      // grands écrans (mur de supervision, écran 4K) ; un facteur fixe
      // l'impose sur ce poste (index.css, --ui-zoom).
      uiScale: "auto",

      toggleTheme: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setTheme: (theme) => set({ theme }),
      toggleRail: () => set((s) => ({ railCollapsed: !s.railCollapsed })),
      setAutoRefresh: (autoRefresh) => set({ autoRefresh }),
      setUiScale: (uiScale) => set({ uiScale }),
    }),
    {
      name: "noc-ui",
      partialize: (s) => ({
        theme: s.theme,
        railCollapsed: s.railCollapsed,
        autoRefresh: s.autoRefresh,
        uiScale: s.uiScale,
      }),
    },
  ),
);

/**
 * PÉRIODE D'OBSERVATION GLOBALE (INC-20, INC-34, AM-30).
 *
 * Un seul sélecteur, dans la barre de filtres, pilote tous les blocs « sur
 * une durée » de tous les écrans : courbes, disponibilité sur la durée, SLA,
 * historique des incidents. Avant, chaque page avait son propre jeu de
 * fenêtres (6 h / 3 j ici, 1 an là, 12 mois ailleurs) et certains blocs
 * restaient « sur 24 h » quel que soit le choix.
 *
 * Mémorisée pour la SESSION du navigateur (sessionStorage) : on la retrouve
 * en changeant de page, pas trois semaines plus tard.
 */
export const WINDOWS = [
  { value: 6, label: "6 h" },
  { value: 24, label: "24 h" },
  { value: 168, label: "7 j" },
  { value: 720, label: "30 j" },
  { value: 2160, label: "90 j" },
  { value: 8760, label: "12 mois" },
];

export function windowLabel(hours) {
  return WINDOWS.find((item) => item.value === hours)?.label ?? `${hours} h`;
}

/** Nombre de jours d'une fenêtre, pour les API en jours (au moins 1). */
export function windowDays(hours) {
  return Math.max(1, Math.min(365, Math.round(hours / 24)));
}

export const useWindowStore = create(
  persist(
    (set) => ({
      hours: 24,
      setHours: (hours) => set({ hours }),
    }),
    { name: "noc-window", storage: createJSONStorage(() => sessionStorage) },
  ),
);

/** Tableaux de bord qui montrent un mois passé quand on en choisit un. */
export const MONTH_ROUTES = [
  "/direction", "/supervision", "/console", "/territoire", "/alertes", "/performance",
];

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

import { create } from "zustand";

const currentPeriod = () => {
  const now = new Date();
  return { month: now.getMonth() + 1, year: now.getFullYear() };
};

const isCurrentPeriod = (month, year) => {
  const now = currentPeriod();
  return month === now.month && year === now.year;
};

export const usePeriodStore = create((set, get) => ({
  ...currentPeriod(),
  // The dashboard is left open for weeks on a NOC screen, so the period can't
  // just be read from the clock at load time — it has to roll over on its own
  // when the month changes (see usePeriodAutoSync). It must not roll over
  // while someone is reading a past month, hence this flag: it is set as soon
  // as a month is picked by hand, and cleared again when that lands back on
  // the live month.
  pinned: false,
  setPeriod: (month, year) =>
    set({ month, year, pinned: !isCurrentPeriod(month, year) }),
  goToPreviousMonth: () => {
    const { month, year, setPeriod } = get();
    if (month === 1) setPeriod(12, year - 1);
    else setPeriod(month - 1, year);
  },
  goToNextMonth: () => {
    const { month, year, setPeriod } = get();
    if (month === 12) setPeriod(1, year + 1);
    else setPeriod(month + 1, year);
  },
  // Realign on the wall clock unless the user pinned a month.
  syncToCurrentMonth: () => {
    const { month, year, pinned } = get();
    if (pinned) return;
    const now = currentPeriod();
    if (now.month !== month || now.year !== year) set(now);
  },
}));

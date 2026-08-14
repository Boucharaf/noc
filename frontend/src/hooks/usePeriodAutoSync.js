import { useEffect } from "react";
import { usePeriodStore } from "../store";

// Keeps the selected period on the current month for a dashboard that is never
// reloaded. Without this the month is frozen at whatever it was when the tab
// was opened, so on the 1st every KPI — including the N / N-1 / N-3 comparison
// — keeps reporting the month that just ended.
//
// A minute is fine: a wall display being one minute late to a month boundary is
// invisible, and the extra checks on visibility/focus catch the common case of
// a laptop that was asleep across midnight.
export const usePeriodAutoSync = (intervalMs = 60_000) => {
  const syncToCurrentMonth = usePeriodStore((s) => s.syncToCurrentMonth);

  useEffect(() => {
    syncToCurrentMonth();

    const id = setInterval(syncToCurrentMonth, intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") syncToCurrentMonth();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", syncToCurrentMonth);

    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", syncToCurrentMonth);
    };
  }, [syncToCurrentMonth, intervalMs]);
};

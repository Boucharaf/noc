import apiClient from "./client";

// Taux de couverture de supervision, global et par site — voir
// app/routes/assets.py::get_coverage. Répond CoverageSummaryOut
// { total_assets, monitored_assets, unmonitored_assets, coverage_pct,
//   by_locality, last_synced_at }.
export const getCoverage = (signal) =>
  apiClient.get("/assets/coverage", { signal }).then((r) => r.data);

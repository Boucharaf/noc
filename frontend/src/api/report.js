import apiClient from "./client";
import { useAuthStore } from "../store/auth";
import { assertPermission, PERMISSIONS } from "./permissions";

export const downloadMonthlyReport = async (month, year, format, { signal } = {}) => {
  assertPermission(useAuthStore.getState().user?.role, PERMISSIONS.DOWNLOAD_REPORT);

  const response = await apiClient.get("/report/monthly", {
    params: { month, year, format },
    responseType: "blob",
    timeout: 30000,
    signal,
  });

  // Piège classique avec responseType: "blob" : si le backend répond une
  // erreur JSON (403, 500, rapport indisponible), axios la livre quand même
  // comme un Blob "application/json" au lieu de rejeter la promesse — on
  // téléchargerait alors un fichier "rapport.pdf" contenant en réalité
  // {"detail": "..."}. On détecte ce cas avant de déclencher le download.
  if (response.data.type === "application/json") {
    const text = await response.data.text();
    const body = JSON.parse(text);
    throw new Error(body.detail || "Le rapport n'a pas pu être généré.");
  }

  const url = URL.createObjectURL(response.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = `rapport-noc-${year}-${String(month).padStart(2, "0")}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
};
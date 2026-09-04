import React, { useState } from "react";
import { MapPinCheck, Navigation, ClipboardCheck, Loader2 } from "lucide-react";
import Card from "../components/Card";
import {
  useMyInterventions,
  useUpdateInterventionStatus,
  useSubmitInterventionReport,
} from "../hooks/useFieldInterventions";

const STATUS_LABEL = {
  scheduled: "Planifiée",
  en_route: "En route",
  on_site: "Sur site",
  done: "Terminée",
  cancelled: "Annulée",
};

const NEXT_STATUS = {
  scheduled: "en_route",
  en_route: "on_site",
};

const NEXT_LABEL = {
  scheduled: "Démarrer (en route)",
  en_route: "Arrivé sur site",
};

// Capture de géolocalisation : un GPS imprécis ou refusé ne doit jamais
// bloquer un agent qui a réellement fait l'intervention — voir la note dans
// field_service.submit_report. Le formulaire attend juste la position avant
// d'activer le bouton, sans jamais la revalider contre le nœud.
const useGeolocation = () => {
  const [coords, setCoords] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const capture = () => {
    if (!navigator.geolocation) {
      setError("Géolocalisation non disponible sur cet appareil.");
      return;
    }
    setLoading(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        });
        setLoading(false);
      },
      (err) => {
        setError(err.message || "Impossible d'obtenir la position.");
        setLoading(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  return { coords, error, loading, capture };
};

const ReportForm = ({ intervention, onSubmitted }) => {
  const [reportText, setReportText] = useState("");
  const geo = useGeolocation();
  const submitReport = useSubmitInterventionReport();

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!geo.coords || !reportText.trim()) return;
    submitReport.mutate(
      {
        interventionId: intervention.id,
        report: {
          reportText: reportText.trim(),
          checkinLatitude: geo.coords.latitude,
          checkinLongitude: geo.coords.longitude,
          photoUrls: [],
        },
      },
      { onSuccess: onSubmitted }
    );
  };

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3">
      <textarea
        value={reportText}
        onChange={(e) => setReportText(e.target.value)}
        placeholder="Compte-rendu de l'intervention (constat, action réalisée, pièces changées…)"
        rows={3}
        className="w-full rounded-lg border px-3 py-2 text-sm outline-none"
        style={{
          borderColor: "var(--color-border-strong)",
          background: "var(--color-surface-2)",
          color: "var(--color-text-primary)",
        }}
      />

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={geo.capture}
          disabled={geo.loading}
          className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[var(--color-surface-2)]"
          style={{ borderColor: "var(--color-border-strong)", color: "var(--color-text-secondary)" }}
        >
          {geo.loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <MapPinCheck className="h-3.5 w-3.5" />
          )}
          {geo.coords ? "Position enregistrée" : "Capturer ma position"}
        </button>
        {geo.error && (
          <span className="text-xs" style={{ color: "var(--color-critical, #d03b3b)" }}>
            {geo.error}
          </span>
        )}
      </div>

      <button
        type="submit"
        disabled={!geo.coords || !reportText.trim() || submitReport.isPending}
        className="w-full rounded-lg py-2 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
        style={{ background: "var(--color-accent)" }}
      >
        {submitReport.isPending ? "Envoi…" : "Clôturer l'intervention"}
      </button>
      {submitReport.isError && (
        <p className="text-xs" style={{ color: "var(--color-critical, #d03b3b)" }}>
          Échec de l'envoi du rapport — réessayez.
        </p>
      )}
    </form>
  );
};

const InterventionCard = ({ intervention }) => {
  const [showReport, setShowReport] = useState(false);
  const updateStatus = useUpdateInterventionStatus();
  const nextStatus = NEXT_STATUS[intervention.status];

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--color-text-primary)" }}>
            {intervention.node_name}
          </p>
          <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>
            {STATUS_LABEL[intervention.status] ?? intervention.status}
            {intervention.incident_id && ` · Incident #${intervention.incident_id}`}
          </p>
        </div>
      </div>

      {intervention.status !== "done" && intervention.status !== "cancelled" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {nextStatus && (
            <button
              onClick={() => updateStatus.mutate({ interventionId: intervention.id, status: nextStatus })}
              disabled={updateStatus.isPending}
              className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-white transition-opacity disabled:opacity-50"
              style={{ background: "var(--color-accent)" }}
            >
              <Navigation className="h-3.5 w-3.5" />
              {NEXT_LABEL[intervention.status]}
            </button>
          )}
          {intervention.status === "on_site" && !showReport && (
            <button
              onClick={() => setShowReport(true)}
              className="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-[var(--color-surface-2)]"
              style={{ borderColor: "var(--color-border-strong)", color: "var(--color-text-primary)" }}
            >
              <ClipboardCheck className="h-3.5 w-3.5" />
              Rédiger le compte-rendu
            </button>
          )}
        </div>
      )}

      {showReport && (
        <ReportForm intervention={intervention} onSubmitted={() => setShowReport(false)} />
      )}

      {intervention.report_text && (
        <p
          className="mt-3 rounded-lg p-2.5 text-xs"
          style={{ background: "var(--color-surface-2)", color: "var(--color-text-secondary)" }}
        >
          {intervention.report_text}
        </p>
      )}
    </Card>
  );
};

const AgentTerrainView = () => {
  const { data: interventions = [], isLoading } = useMyInterventions();
  const active = interventions.filter((i) => i.status !== "done" && i.status !== "cancelled");
  const past = interventions.filter((i) => i.status === "done" || i.status === "cancelled");

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-lg font-bold" style={{ color: "var(--color-text-primary)" }}>
          Mes tournées
        </h1>
        <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
          Interventions terrain qui vous sont assignées.
        </p>
      </div>

      {isLoading && (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          Chargement…
        </p>
      )}

      {!isLoading && active.length === 0 && (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          Aucune intervention en cours.
        </p>
      )}

      <div className="space-y-3">
        {active.map((i) => (
          <InterventionCard key={i.id} intervention={i} />
        ))}
      </div>

      {past.length > 0 && (
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--color-text-secondary)" }}>
            Terminées
          </h2>
          <div className="space-y-3">
            {past.map((i) => (
              <InterventionCard key={i.id} intervention={i} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentTerrainView;

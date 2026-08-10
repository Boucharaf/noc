import React, { useMemo, useState } from "react";
import { Map as MapIcon, X } from "lucide-react";
import Card from "../components/Card";
import BurkinaFasoMap from "../components/map/BurkinaFasoMap";
import { SeverityBadge } from "../components/Badge";
import { useKpiLocalitiesMap } from "../hooks/useKPI";
import { useOpenAlerts } from "../hooks/useRealtime";
import { SEVERITY_COLOR } from "../theme/colors";
import { formatAge } from "../utils/format";

const SEVERITIES = ["critical", "high", "medium", "low"];
const SEVERITY_LABEL = {
  critical: "Critique",
  high: "Élevée",
  medium: "Moyenne",
  low: "Faible",
};

// The panel lists a locality's own open incidents. 100 is the API's ceiling;
// Ouagadougou alone has ~245 open, so the list is explicitly a "oldest first,
// first 100" view rather than pretending to be exhaustive.
const PANEL_LIMIT = 100;

const ALL_REGIONS = "all";

// On this page the markers must mean the same thing as the filter chips above
// them. Colouring by monthly availability instead made ticking "Moyenne"
// (yellow) show a map of red dots, because 61 of 76 localities sit under 90%
// availability whatever you filter on.
const severityScheme = (severities) => ({
  colorFor: (l) =>
    SEVERITY_COLOR[
      SEVERITIES.find((s) => severities.has(s) && (l.by_severity?.[s] ?? 0) > 0)
    ] ?? SEVERITY_COLOR.low,
  legend: SEVERITIES.filter((s) => severities.has(s)).map((s) => ({
    color: SEVERITY_COLOR[s],
    label: SEVERITY_LABEL[s],
  })),
});

const MapView = () => {
  const { data: localities = [], isLoading } = useKpiLocalitiesMap();
  const [selectedId, setSelectedId] = useState(null);
  const [severities, setSeverities] = useState(new Set(SEVERITIES));
  const [region, setRegion] = useState(ALL_REGIONS);

  const { data: alerts = [], isLoading: alertsLoading } = useOpenAlerts(
    PANEL_LIMIT,
    selectedId,
  );

  const regions = useMemo(
    () => [...new Set(localities.map((l) => l.region))].sort(),
    [localities],
  );

  // Markers are sized by the incidents matching the severity filter for the
  // selected month, so the period picker drives this page like every other
  // tab. A locality with nothing matching is removed rather than drawn at zero.
  const points = useMemo(
    () =>
      localities
        .map((l) => ({
          ...l,
          matching: SEVERITIES.filter((s) => severities.has(s)).reduce(
            (sum, s) => sum + (l.by_severity?.[s] ?? 0),
            0,
          ),
        }))
        .filter((l) => l.matching > 0)
        .filter((l) => region === ALL_REGIONS || l.region === region)
        .map((l) => ({ ...l, total_incidents: l.matching })),
    [localities, severities, region],
  );

  const totalShown = points.reduce((sum, p) => sum + p.matching, 0);

  // Derived, never stored: a copy taken at click time goes stale the moment the
  // filter changes, and the panel then contradicts the marker it came from
  // ("242 incidents" beside a marker reading 115). A selection filtered out of
  // view closes the panel, which is the honest outcome.
  const selected = useMemo(
    () => points.find((p) => p.locality_id === selectedId) ?? null,
    [points, selectedId],
  );

  const toggleSeverity = (severity) =>
    setSeverities((prev) => {
      const next = new Set(prev);
      if (next.has(severity)) next.delete(severity);
      else next.add(severity);
      return next;
    });

  const visibleAlerts = alerts.filter((a) => severities.has(a.severity));
  const scheme = useMemo(() => severityScheme(severities), [severities]);

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MapIcon className="h-5 w-5" style={{ color: "var(--color-accent)" }} />
          <div>
            <h2
              className="text-xl font-bold"
              style={{ color: "var(--color-text-primary)" }}
            >
              Carte des Incidents
            </h2>
            <p className="text-sm" style={{ color: "var(--color-text-secondary)" }}>
              {isLoading
                ? "Chargement…"
                : `${totalShown} incident(s) sur ${points.length} localité(s)`}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {SEVERITIES.map((severity) => {
            const active = severities.has(severity);
            return (
              <button
                key={severity}
                type="button"
                onClick={() => toggleSeverity(severity)}
                aria-pressed={active}
                className="flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-opacity"
                style={{
                  borderColor: active
                    ? SEVERITY_COLOR[severity]
                    : "var(--color-border)",
                  color: active
                    ? SEVERITY_COLOR[severity]
                    : "var(--color-text-muted)",
                  background: active ? "var(--color-surface-2)" : "transparent",
                  opacity: active ? 1 : 0.6,
                }}
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: SEVERITY_COLOR[severity] }}
                />
                {SEVERITY_LABEL[severity]}
              </button>
            );
          })}

          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="rounded-md border px-2 py-1.5 text-xs"
            style={{
              borderColor: "var(--color-border)",
              background: "var(--color-surface)",
              color: "var(--color-text-primary)",
            }}
          >
            <option value={ALL_REGIONS}>Toutes les régions</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid min-h-[560px] flex-1 auto-rows-fr grid-cols-1 gap-4 lg:grid-cols-3">
        <Card
          title="Carte de Supervision"
          subtitle="Taille = incidents filtrés · couleur = sévérité la plus haute"
          className="flex h-full flex-col lg:col-span-2"
          bodyClassName="flex min-h-0 flex-1 flex-col"
        >
          {points.length === 0 && !isLoading ? (
            // Silence here reads as a broken map. Your network currently has no
            // "Faible" incidents at all, so ticking only that chip empties the
            // map — say so rather than showing an empty country.
            <div
              className="flex min-h-[420px] flex-1 items-center justify-center rounded-lg border p-6 text-center text-sm"
              style={{
                borderColor: "var(--color-border)",
                color: "var(--color-text-muted)",
              }}
            >
              Aucun incident pour ce filtre.
              <br />
              Élargissez la sévérité ou la région.
            </div>
          ) : (
            <BurkinaFasoMap
              localities={points}
              selectedLocalityId={selectedId}
              onSelect={setSelectedId}
              minHeight={420}
              scheme={scheme}
            />
          )}
        </Card>

        <Card
          title={selected ? selected.locality : "Incidents"}
          subtitle={
            selected
              ? selected.region
              : "Cliquez une localité sur la carte pour voir ses incidents"
          }
          className="flex h-full flex-col"
          bodyClassName="flex min-h-0 flex-1 flex-col p-0"
        >
          {selected && (
            <div
              className="flex shrink-0 items-center justify-between border-b px-4 py-2"
              style={{ borderColor: "var(--color-border)" }}
            >
              {/* Two different numbers, so both are named. `matching` is the
                  locality's true open count for the current filter; the list
                  itself is the oldest PANEL_LIMIT the API will return, then
                  filtered client-side — so it can be short of the total. */}
              <span
                className="text-xs"
                style={{ color: "var(--color-text-secondary)" }}
              >
                {visibleAlerts.length} affiché(s)
                {selected.matching > visibleAlerts.length &&
                  ` · ${selected.matching} au total`}
              </span>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                className="flex items-center gap-1 text-xs hover:underline"
                style={{ color: "var(--color-text-muted)" }}
              >
                <X className="h-3 w-3" />
                Fermer
              </button>
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto">
            {!selected && (
              <p
                className="p-5 text-sm"
                style={{ color: "var(--color-text-muted)" }}
              >
                Aucune localité sélectionnée.
              </p>
            )}
            {selected && alertsLoading && (
              <p
                className="p-5 text-sm"
                style={{ color: "var(--color-text-muted)" }}
              >
                Chargement…
              </p>
            )}
            {selected && !alertsLoading && visibleAlerts.length === 0 && (
              <p
                className="p-5 text-sm"
                style={{ color: "var(--color-text-muted)" }}
              >
                Aucun incident pour ce filtre.
              </p>
            )}
            {selected &&
              !alertsLoading &&
              visibleAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="border-b px-4 py-3 last:border-b-0"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className="truncate font-mono text-xs"
                      style={{ color: "var(--color-text-secondary)" }}
                      title={`${alert.node_code} — ${alert.node_name}`}
                    >
                      {alert.node_code}
                    </span>
                    <SeverityBadge severity={alert.severity} />
                  </div>
                  <p
                    className="mt-1 text-sm"
                    style={{ color: "var(--color-text-primary)" }}
                  >
                    {alert.description}
                  </p>
                  <p
                    className="mt-0.5 truncate text-xs"
                    style={{ color: "var(--color-text-muted)" }}
                    title={alert.node_name}
                  >
                    {alert.node_name} — {formatAge(alert.age_minutes)}
                  </p>
                </div>
              ))}
          </div>
        </Card>
      </div>
    </div>
  );
};

export default MapView;

import React, { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { MapPin } from "lucide-react";
import Card from "../components/Card";
import NodeList from "../components/NodeList";
import IncidentTable from "../components/IncidentTable";
import BurkinaFasoMap from "../components/map/BurkinaFasoMap";
import LocalityBulletList from "../components/map/LocalityBulletList";
import { useKpiLocalitiesMap, useLocalityNodes } from "../hooks/useKPI";
import { useOpenAlerts } from "../hooks/useRealtime";

const LocalityView = () => {
  const location = useLocation();
  const { data: localities = [], isLoading: localitiesLoading } =
    useKpiLocalitiesMap();
  // Preselects the locality clicked on the map/bullet list in Vue Globale, if
  // navigation carried one; otherwise falls back to the busiest locality below.
  const [localityId, setLocalityId] = useState(
    location.state?.localityId ?? null,
  );

  useEffect(() => {
    if (!localityId && localities.length) {
      setLocalityId(
        [...localities].sort((a, b) => b.total_incidents - a.total_incidents)[0]
          .locality_id,
      );
    }
  }, [localities, localityId]);

  const { data: localityDetail, isLoading: nodesLoading } =
    useLocalityNodes(localityId);
  const { data: alerts = [] } = useOpenAlerts(100);

  const selectedLocalityName = localityDetail?.locality;
  const localityIncidents = selectedLocalityName
    ? alerts.filter((a) => a.locality === selectedLocalityName)
    : [];

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-2">
        <MapPin className="h-5 w-5" style={{ color: "var(--color-accent)" }} />
        <div>
          <h2
            className="text-xl font-bold"
            style={{ color: "var(--color-text-primary)" }}
          >
            Vue par Localité
          </h2>
          <p
            className="text-sm"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Sélectionnez une localité sur la carte ou dans la liste pour
            l'explorer
          </p>
        </div>
      </div>

      <div className="grid min-h-[320px] flex-1 auto-rows-fr grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-5">
        <Card
          title="Sélection"
          className="flex h-full flex-col md:col-span-2 lg:col-span-2"
          bodyClassName="flex min-h-0 flex-1 flex-col"
        >
          {localitiesLoading ? (
            <div
              className="flex h-full min-h-32 items-center justify-center text-sm"
              style={{ color: "var(--color-text-muted)" }}
            >
              Chargement…
            </div>
          ) : (
            <>
              <div className="min-h-0 flex-[3]">
                <BurkinaFasoMap
                  localities={localities}
                  selectedLocalityId={localityId}
                  onSelect={setLocalityId}
                  height="100%"
                />
              </div>
              <div
                className="mt-4 flex min-h-0 flex-[2] flex-col border-t pt-3"
                style={{ borderColor: "var(--color-border)" }}
              >
                <LocalityBulletList
                  localities={localities}
                  selectedLocalityId={localityId}
                  onSelect={setLocalityId}
                  maxHeight="100%"
                />
              </div>
            </>
          )}
        </Card>

        <div className="h-full md:col-span-1 lg:col-span-1">
          <NodeList
            nodes={localityDetail?.nodes ?? []}
            loading={nodesLoading}
          />
        </div>

        <div className="h-full md:col-span-1 lg:col-span-2">
          <IncidentTable
            title={`Alertes ouvertes — ${selectedLocalityName ?? ""}`}
            incidents={localityIncidents}
            loading={nodesLoading}
          />
        </div>
      </div>
    </div>
  );
};

export default LocalityView;

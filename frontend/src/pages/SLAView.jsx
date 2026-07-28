import React from "react";
import { ShieldAlert } from "lucide-react";
import SLATracker from "../components/SLATracker";
import AlertFeed from "../components/AlertFeed";
import { useSLA } from "../hooks/useKPI";

const SLAView = () => {
  const { data: sla, isLoading } = useSLA();

  return (
    <div className="flex min-h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-2">
        <ShieldAlert
          className="h-5 w-5"
          style={{ color: "var(--color-accent)" }}
        />
        <div>
          <h2
            className="text-xl font-bold"
            style={{ color: "var(--color-text-primary)" }}
          >
            SLA & Alertes Temps Réel
          </h2>
          <p
            className="text-sm"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Indicateurs contractuels vs. cibles — {sla?.period?.label ?? "…"}
          </p>
        </div>
      </div>
      <div className="grid min-h-[320px] flex-1 auto-rows-fr grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="h-full min-h-0 space-y-4 overflow-y-auto pr-1">
          {isLoading && (
            <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
              Chargement…
            </p>
          )}
          {(sla?.indicators ?? []).map((indicator) => (
            <SLATracker
              key={indicator.metric}
              metric={indicator.metric}
              value={indicator.value}
              target={indicator.target}
            />
          ))}
        </div>
        <div className="h-full">
          <AlertFeed />
        </div>
      </div>
    </div>
  );
};

export default SLAView;

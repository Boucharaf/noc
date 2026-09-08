import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Maximize2, X } from "lucide-react";

import { Donut } from "../components/charts";
import { SeverityBadge } from "../components/ui/Badge";
import { ageFrom, ellipsis, num, pct } from "../lib/format";
import { availabilityColor, nodeStateMeta, severityMeta } from "../lib/vocabulary";
import { useClock } from "../hooks/useClock";
import { useRealtime } from "../hooks/useRealtime";
import {
  useAlertSummary,
  useNetworkKpi,
  useNodeStates,
  useNodesDown,
  useOpenAlerts,
} from "../hooks/queries";

/**
 * Mode mur d'écrans.
 *
 * Destiné à un écran de 55 pouces lu à trois mètres, sans souris. Tout y
 * est plus grand, il n'y a aucun contrôle de navigation, et le contenu
 * se limite à ce qu'on doit voir sans lire : combien d'alertes, de
 * quelle gravité, depuis combien de temps, et quels équipements sont
 * tombés.
 *
 * Aucune interaction n'est proposée à dessein — un écran mural n'a pas
 * d'opérateur devant lui. La seule sortie est la touche Échap, indiquée
 * en clair, parce qu'un écran sans issue visible finit par être quitté
 * en fermant l'onglet.
 */
export default function WallboardPage() {
  const navigate = useNavigate();
  const now = useClock();

  // Le mur d'écrans vit hors de la coque : il doit donc ouvrir son propre
  // flux temps réel, sinon il n'afficherait une nouvelle alerte qu'au
  // prochain sondage — jusqu'à vingt secondes de retard sur un écran dont
  // c'est justement la seule raison d'être.
  const { status: realtimeStatus } = useRealtime();

  const summary = useAlertSummary();
  const alerts = useOpenAlerts({ limit: 14 });
  const nodeStates = useNodeStates();
  const nodesDown = useNodesDown();
  const network = useNetworkKpi({ hours: 24 });

  const [fullscreenAvailable] = useState(
    () => typeof document !== "undefined" && document.fullscreenEnabled,
  );

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") navigate(-1);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navigate]);

  const s = summary.data;
  const states = nodeStates.data;

  const severities = [
    { key: "critical", value: s?.critical ?? 0 },
    { key: "high", value: s?.high ?? 0 },
    { key: "medium", value: s?.medium ?? 0 },
    { key: "low", value: s?.low ?? 0 },
  ];

  return (
    <div
      className="wallboard fixed inset-0 z-50 flex flex-col overflow-hidden"
      style={{ background: "var(--page)" }}
    >
      {/* --- Bandeau --- */}
      <header
        className="flex items-center gap-4 px-4 border-b shrink-0"
        style={{ height: 60, borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <span className="live-dot" style={{ width: 9, height: 9 }} />
        <h1 className="text-[22px] font-semibold tracking-tight">NOC RESINA</h1>
        <span className="text-[14px]" style={{ color: "var(--ink-3)" }}>
          Supervision du réseau de l'administration
        </span>
        <span
          className="text-[13px] flex items-center gap-1.5"
          style={{
            color:
              realtimeStatus === "live" ? "var(--state-up)" : "var(--sev-critical)",
          }}
          title="État du flux temps réel"
        >
          <span
            className={realtimeStatus === "live" ? "live-dot" : "dot"}
            style={{
              background:
                realtimeStatus === "live" ? "var(--state-up)" : "var(--sev-critical)",
              width: 8,
              height: 8,
            }}
          />
          {realtimeStatus === "live" ? "flux actif" : "flux coupé"}
        </span>

        <time className="num ml-auto text-[26px] tracking-tight">
          {now.toLocaleTimeString("fr-FR", { hour12: false })}
        </time>
        <span className="text-[14px] capitalize" style={{ color: "var(--ink-3)" }}>
          {now.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}
        </span>

        {fullscreenAvailable && (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => document.documentElement.requestFullscreen?.()}
            title="Plein écran"
          >
            <Maximize2 size={16} />
          </button>
        )}
        <button type="button" className="btn btn-ghost" onClick={() => navigate(-1)} title="Quitter (Échap)">
          <X size={16} />
        </button>
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-12 gap-3 p-3">
        {/* --- Compteurs de gravité --- */}
        <div className="col-span-3 flex flex-col gap-3 min-h-0">
          {severities.map((entry) => {
            const meta = severityMeta(entry.key);
            const critical = entry.key === "critical" && entry.value > 0;
            return (
              <div
                key={entry.key}
                className="panel flex-1 flex flex-col items-center justify-center"
                style={{
                  borderColor: entry.value ? meta.color : "var(--border)",
                  background: entry.value
                    ? `color-mix(in srgb, ${meta.color} 9%, var(--surface))`
                    : "var(--surface)",
                }}
              >
                <span
                  className={`num font-bold leading-none ${critical ? "blink-critical" : ""}`}
                  style={{ fontSize: 62, color: entry.value ? meta.color : "var(--ink-3)" }}
                >
                  {num(entry.value, "0")}
                </span>
                <span
                  className="text-[15px] font-semibold uppercase tracking-[0.1em] mt-1"
                  style={{ color: "var(--ink-2)" }}
                >
                  {meta.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* --- Alertes --- */}
        <div className="col-span-6 panel min-h-0 flex flex-col">
          <header className="panel-head">
            <h2 className="panel-title">Alertes en cours</h2>
            <span className="ml-auto num text-[15px]" style={{ color: "var(--ink-2)" }}>
              {num(s?.total_open, "0")} ouvertes · {num(s?.unacknowledged, "0")} non acquittées
            </span>
          </header>
          <div className="flex-1 overflow-hidden">
            <table className="tbl">
              <tbody>
                {(alerts.data ?? []).map((alert) => (
                  <tr key={alert.id} className={`sev-edge sev-edge-${alert.severity}`}>
                    <td style={{ width: 96 }}>
                      <SeverityBadge severity={alert.severity} short />
                    </td>
                    <td style={{ width: 90 }} className="num">
                      <span
                        style={{
                          color:
                            (alert.age_minutes ?? 0) > 240
                              ? "var(--sev-medium)"
                              : "var(--ink-2)",
                        }}
                      >
                        {ageFrom(alert.detected_at)}
                      </span>
                    </td>
                    <td style={{ width: 210 }} className="font-medium">
                      {alert.node_name}
                    </td>
                    <td style={{ width: 150, color: "var(--ink-3)" }}>{alert.locality}</td>
                    <td style={{ color: "var(--ink-2)" }}>
                      {ellipsis(alert.description, 62)}
                    </td>
                  </tr>
                ))}
                {(alerts.data ?? []).length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-center" style={{ height: 120, color: "var(--state-up)" }}>
                      <span style={{ fontSize: 22 }}>Aucune alerte ouverte</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* --- Parc et réseau --- */}
        <div className="col-span-3 flex flex-col gap-3 min-h-0">
          <div className="panel p-3 flex items-center gap-3">
            <Donut
              size={128}
              thickness={15}
              centerValue={num(states?.total, "0")}
              centerLabel="équip."
              segments={[
                { key: "down", label: "HS", value: states?.down ?? 0, color: "var(--state-down)" },
                {
                  key: "degraded",
                  label: "Dégradés",
                  value: states?.degraded ?? 0,
                  color: "var(--state-degraded)",
                },
                { key: "silent", label: "Muets", value: states?.silent ?? 0, color: "var(--state-silent)" },
                {
                  key: "maintenance",
                  label: "Maintenance",
                  value: states?.maintenance ?? 0,
                  color: "var(--state-maintenance)",
                },
                { key: "up", label: "Nominaux", value: states?.up ?? 0, color: "var(--state-up)" },
              ]}
            />
            <ul className="flex-1 space-y-1">
              {["down", "degraded", "silent", "up"].map((state) => {
                const meta = nodeStateMeta(state);
                return (
                  <li key={state} className="flex items-center gap-2 text-[14px]">
                    <span className="dot" style={{ background: meta.color, width: 9, height: 9 }} />
                    <span className="flex-1" style={{ color: "var(--ink-2)" }}>
                      {meta.label}
                    </span>
                    <span className="num font-semibold">{num(states?.[state], "0")}</span>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="panel p-3">
            <div className="text-[13px] uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>
              Disponibilité 24 h
            </div>
            <div
              className="num font-bold leading-none mt-1"
              style={{
                fontSize: 44,
                color: availabilityColor(network.data?.availability_pct),
              }}
            >
              {pct(network.data?.availability_pct, 2)}
            </div>
          </div>

          <div className="panel min-h-0 flex flex-col flex-1">
            <header className="panel-head">
              <h2 className="panel-title">Équipements hors service</h2>
            </header>
            <ul className="flex-1 overflow-hidden divide-y" style={{ borderColor: "var(--border)" }}>
              {(nodesDown.data ?? []).slice(0, 8).map((node) => (
                <li key={node.node_id} className="px-3 py-2 flex items-center gap-2">
                  <span className="dot" style={{ background: "var(--state-down)", width: 9, height: 9 }} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-[15px] font-medium truncate">{node.node_name}</span>
                    <span className="block text-[12px]" style={{ color: "var(--ink-3)" }}>
                      {node.locality}
                    </span>
                  </span>
                  <span className="num text-[14px]" style={{ color: "var(--sev-critical)" }}>
                    {node.since ? ageFrom(node.since) : "—"}
                  </span>
                </li>
              ))}
              {(nodesDown.data ?? []).length === 0 && (
                <li className="px-3 py-6 text-center text-[16px]" style={{ color: "var(--state-up)" }}>
                  Parc nominal
                </li>
              )}
            </ul>
          </div>
        </div>
      </div>

      <footer
        className="shrink-0 px-4 py-1.5 border-t text-[12px] flex items-center gap-4"
        style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
      >
        <span>Échap pour quitter le mode mur</span>
        {s?.oldest_unacknowledged_at && (
          <span className="ml-auto">
            Plus ancienne non acquittée :{" "}
            <span className="num" style={{ color: "var(--sev-medium)" }}>
              {ageFrom(s.oldest_unacknowledged_at)}
            </span>
          </span>
        )}
      </footer>
    </div>
  );
}

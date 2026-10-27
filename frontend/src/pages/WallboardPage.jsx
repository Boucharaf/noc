import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Maximize2, X } from "lucide-react";

import { Badge, SeverityBadge } from "../components/ui/Badge";
import { ageFrom, ellipsis, num, pct } from "../lib/format";
import { slaStatusMeta } from "../lib/itop";
import { availabilityColor, severityMeta } from "../lib/vocabulary";
import { useClock } from "../hooks/useClock";
import { useRealtime } from "../hooks/useRealtime";
import TerritoryMap from "../components/domain/TerritoryMap";
import { useGeoBreakdown, useItopIncidents, useNetworkKpi } from "../hooks/queries";

/**
 * Mode mur d'écrans — le résumé des INCIDENTS iTop.
 *
 * Un raccourci pour l'exploitant qui n'a pas le temps de parcourir le
 * NOC : un coup d'œil doit suffire à savoir combien d'incidents sont
 * ouverts, lesquels sont graves, lesquels dépassent leur engagement ou
 * n'ont personne, et où ils se trouvent. Les alertes des outils n'y
 * figurent pas : elles ont leur écran, et un mur qui mélange signaux
 * techniques et tickets ne se lit plus à trois mètres.
 *
 * Toujours sur tout le réseau, quel que soit le périmètre choisi dans le
 * NOC : un écran de salle ne doit pas rester filtré sur une province parce
 * que quelqu'un l'a consultée la veille.
 *
 * Aucune interaction à dessein — un écran mural n'a pas d'opérateur devant
 * lui. La seule sortie est la touche Échap, indiquée en clair.
 */
const ROWS = 12;

function HeadlineKpi({ label, value, color, emphasis = false }) {
  return (
    <div
      className="flex-1 min-w-0 flex flex-col justify-center px-4 border-l"
      style={{ borderColor: "var(--border)" }}
    >
      <span
        className={`num font-bold leading-none ${emphasis ? "blink-critical" : ""}`}
        style={{ fontSize: 34, color: color ?? "var(--ink)" }}
      >
        {value}
      </span>
      <span
        className="text-[12px] uppercase tracking-[0.08em] mt-1 whitespace-nowrap"
        style={{ color: "var(--ink-3)" }}
      >
        {label}
      </span>
    </div>
  );
}

export default function WallboardPage() {
  const navigate = useNavigate();
  const now = useClock();
  const { status: realtimeStatus } = useRealtime();

  const incidents = useItopIncidents({ limit: ROWS }, { global: true });
  const network = useNetworkKpi();
  // Tout le réseau, quel que soit le périmètre choisi dans le NOC.
  const geo = useGeoBreakdown({});

  // Alarme visuelle : un incident critique de plus qu'au rafraîchissement
  // précédent fait clignoter le cadre du mur pendant une minute — sur un
  // écran que personne ne fixe, c'est ce qui attire l'œil.
  const [alarm, setAlarm] = useState(false);
  const previousCritical = useRef(null);
  const critical = incidents.data?.by_severity?.critical;
  useEffect(() => {
    if (critical == null) return undefined;
    const before = previousCritical.current;
    previousCritical.current = critical;
    if (before == null || critical <= before) return undefined;
    setAlarm(true);
    const timer = setTimeout(() => setAlarm(false), 60_000);
    return () => clearTimeout(timer);
  }, [critical]);

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

  const d = incidents.data;
  const bySeverity = d?.by_severity ?? {};
  const regions = (d?.network_by_region ?? []).slice(0, 14);
  // Échelle des barres sur les seules régions connues : les tickets sans
  // localité, souvent majoritaires, écraseraient toutes les autres barres.
  const regionMax = Math.max(
    1,
    ...regions.filter((row) => !row.region.endsWith("non renseignée")).map((row) => row.count),
  );
  const live = realtimeStatus === "live";

  return (
    <div
      className={`wallboard fixed inset-0 z-50 flex flex-col overflow-hidden ${alarm ? "wall-alarm" : ""}`}
      style={{ background: "var(--page)" }}
    >
      {/* --- Bandeau : identité, chiffres clés, heure --- */}
      <header
        className="flex items-stretch border-b shrink-0"
        style={{ height: 88, borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div className="flex flex-col justify-center px-4 shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="live-dot" style={{ width: 10, height: 10 }} />
            <h1 className="text-[24px] font-semibold tracking-tight">NOC RESINA</h1>
          </div>
          <span className="text-[13px]" style={{ color: "var(--ink-3)" }}>
            Incidents iTop · tout le réseau
          </span>
        </div>

        <HeadlineKpi label="Incidents ouverts" value={num(d?.total, "0")} />
        <HeadlineKpi
          label="SLA dépassé"
          value={num(d?.sla_breached, "0")}
          color={d?.sla_breached ? "var(--sev-critical)" : "var(--state-up)"}
        />
        <HeadlineKpi
          label="Non affectés"
          value={num(d?.unassigned, "0")}
          color={d?.unassigned ? "var(--sev-high)" : "var(--state-up)"}
        />
        <HeadlineKpi
          label="Nouveaux (1 h)"
          value={num(d?.opened_last_hour, "0")}
          color={d?.opened_last_hour ? "var(--sev-medium)" : undefined}
        />
        <HeadlineKpi
          label="Disponibilité du parc"
          value={pct(network.data?.availability_pct, 1)}
          color={availabilityColor(network.data?.availability_pct)}
        />

        <div className="flex items-center gap-3 pl-4 pr-3 border-l shrink-0" style={{ borderColor: "var(--border)" }}>
          <div className="flex flex-col items-end">
            <time className="num text-[30px] leading-none tracking-tight">
              {now.toLocaleTimeString("fr-FR", { hour12: false })}
            </time>
            <span className="text-[13px] capitalize mt-1" style={{ color: "var(--ink-3)" }}>
              {now.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" })}
            </span>
          </div>
          <span
            className="text-[12px] flex items-center gap-1.5"
            style={{ color: live ? "var(--state-up)" : "var(--sev-critical)" }}
            title="État du flux temps réel"
          >
            <span
              className={live ? "live-dot" : "dot"}
              style={{
                background: live ? "var(--state-up)" : "var(--sev-critical)",
                width: 8,
                height: 8,
              }}
            />
            {live ? "direct" : "flux coupé"}
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
        </div>
      </header>

      <div className="flex-1 min-h-0 grid grid-cols-12 gap-3 p-3">
        {/* --- Gravité des incidents --- */}
        <div className="col-span-2 flex flex-col gap-3 min-h-0">
          {["critical", "high", "medium", "low"].map((key) => {
            const meta = severityMeta(key);
            const value = bySeverity[key] ?? 0;
            return (
              <div
                key={key}
                className="panel flex-1 flex flex-col items-center justify-center"
                style={{
                  borderColor: value ? meta.color : "var(--border)",
                  background: value
                    ? `color-mix(in srgb, ${meta.color} 9%, var(--surface))`
                    : "var(--surface)",
                }}
              >
                <span
                  className={`num font-bold leading-none ${key === "critical" && value ? "blink-critical" : ""}`}
                  style={{ fontSize: 60, color: value ? meta.color : "var(--ink-3)" }}
                >
                  {num(value, "0")}
                </span>
                <span
                  className="text-[14px] font-semibold uppercase tracking-[0.1em] mt-1"
                  style={{ color: "var(--ink-2)" }}
                >
                  {meta.label}
                </span>
              </div>
            );
          })}
        </div>

        {/* --- Incidents prioritaires --- */}
        <div className="col-span-7 panel min-h-0 flex flex-col">
          <header className="panel-head">
            <h2 className="panel-title">Incidents prioritaires</h2>
            <span className="ml-auto text-[14px]" style={{ color: "var(--ink-3)" }}>
              par gravité, puis du plus récent
            </span>
          </header>
          <div className="flex-1 overflow-hidden">
            <table className="tbl" style={{ tableLayout: "fixed", width: "100%" }}>
              <tbody>
                {(d?.incidents ?? []).map((row) => {
                  const sla = slaStatusMeta(row.sla?.ttr_status);
                  return (
                    <tr key={row.key} className={`sev-edge sev-edge-${row.severity}`}>
                      <td style={{ width: 92 }}>
                        <SeverityBadge severity={row.severity} short />
                      </td>
                      <td className="min-w-0">
                        <span className="block text-[16px] font-medium truncate" title={row.title}>
                          {row.title}
                        </span>
                        <span className="block text-[13px] truncate" style={{ color: "var(--ink-3)" }}>
                          <span className="num">{row.ref}</span>
                          {" · "}
                          {row.node_name ?? "équipement non identifié"}
                          {row.site || row.province
                            ? ` · ${[row.site, row.province].filter(Boolean).join(", ")}`
                            : ""}
                        </span>
                      </td>
                      <td style={{ width: 150 }} className="text-[14px] truncate">
                        {row.agent ? (
                          <span style={{ color: "var(--ink-2)" }}>{ellipsis(row.agent, 18)}</span>
                        ) : (
                          <span style={{ color: "var(--sev-high)" }}>non affecté</span>
                        )}
                      </td>
                      <td style={{ width: 96 }} className="num text-[15px] text-right">
                        {ageFrom(row.opened_at)}
                      </td>
                      <td style={{ width: 132 }} className="text-right">
                        <Badge color={sla.color}>{sla.label}</Badge>
                      </td>
                    </tr>
                  );
                })}
                {d && d.incidents.length === 0 && (
                  <tr>
                    <td className="text-center" style={{ height: 160, color: "var(--state-up)" }}>
                      <span style={{ fontSize: 24 }}>Aucun incident iTop ouvert</span>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {d && d.total > d.incidents.length && (
            <footer
              className="px-3 py-1.5 border-t text-[13px]"
              style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
            >
              + {num(d.total - d.incidents.length)} autre(s) incident(s) ouvert(s)
            </footer>
          )}
        </div>

        {/* --- Où sont les incidents --- */}
        <div className="col-span-3 flex flex-col gap-3 min-h-0">
          <div className="panel overflow-hidden shrink-0">
            <header className="panel-head">
              <h2 className="panel-title">Carte des incidents</h2>
            </header>
            <TerritoryMap
              level="region"
              rows={geo.data?.rows}
              height={250}
              defaultMetric="incidents"
              controls={false}
            />
          </div>
          <div className="panel min-h-0 flex flex-col flex-1">
            <header className="panel-head">
              <h2 className="panel-title">Par région</h2>
            </header>
            <ul className="flex-1 overflow-hidden px-3 py-2 space-y-2">
              {regions.map((row) => {
                const unknown = row.region.endsWith("non renseignée");
                return (
                  <li key={row.region}>
                    <div className="flex items-baseline gap-2 text-[15px]">
                      <span
                        className="flex-1 truncate"
                        style={{
                          color: unknown ? "var(--ink-3)" : "var(--ink-2)",
                          fontStyle: unknown ? "italic" : undefined,
                        }}
                      >
                        {unknown ? "Sans localité" : row.region}
                      </span>
                      <span className="num font-semibold">{num(row.count)}</span>
                    </div>
                    <div className="h-[5px] rounded-full mt-1" style={{ background: "var(--surface-inset)" }}>
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${Math.min(100, (100 * row.count) / regionMax)}%`,
                          background: unknown ? "var(--ink-3)" : "var(--accent)",
                        }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          <div className="panel p-3">
            <div className="text-[13px] uppercase tracking-[0.08em]" style={{ color: "var(--ink-3)" }}>
              Plus ancien ticket ouvert
            </div>
            <div className="num font-bold leading-none mt-1" style={{ fontSize: 38, color: "var(--sev-medium)" }}>
              {ageFrom(d?.oldest_opened_at)}
            </div>
          </div>
        </div>
      </div>

      <footer
        className="shrink-0 px-4 py-1.5 border-t text-[12px] flex items-center gap-4"
        style={{ borderColor: "var(--border)", color: "var(--ink-3)" }}
      >
        <span>Échap pour quitter le mode mur</span>
        {d?.stale && (
          <span style={{ color: "var(--sev-critical)" }}>
            Données iTop non rafraîchies depuis {Math.round((d.snapshot_age_s ?? 0) / 60)} min
          </span>
        )}
        <span className="ml-auto">Source : iTop · alertes des outils dans le NOC (« Alertes outils »)</span>
      </footer>
    </div>
  );
}

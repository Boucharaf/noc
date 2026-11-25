import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Maximize2, Volume2, VolumeX, X } from "lucide-react";

import { Badge, SeverityBadge } from "../components/ui/Badge";
import { ageFrom, ellipsis, num, availabilityPct } from "../lib/format";
import { helpFor } from "../lib/glossary";
import { slaStatusMeta } from "../lib/itop";
import { fleetColor, severityMeta } from "../lib/vocabulary";
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

// AM-21 : la carte change de vue toutes les 30 s — incidents, équipements en
// panne, disponibilité — pour qu'un mur sans opérateur montre tout.
const MAP_VIEWS = [
  { metric: "incidents", label: "Carte des incidents" },
  { metric: "down", label: "Carte des équipements en panne" },
  { metric: "availability", label: "Carte de la disponibilité" },
];
const ROTATION_MS = 30_000;

/** Bip court (Web Audio) : pas de fichier son à servir ni à mettre en cache. */
function beep() {
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    const context = new Context();
    [0, 0.35].forEach((offset) => {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = 880;
      gain.gain.setValueAtTime(0.0001, context.currentTime + offset);
      gain.gain.exponentialRampToValueAtTime(0.3, context.currentTime + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + offset + 0.25);
      oscillator.connect(gain).connect(context.destination);
      oscillator.start(context.currentTime + offset);
      oscillator.stop(context.currentTime + offset + 0.3);
    });
    setTimeout(() => context.close(), 1000);
  } catch {
    // Son indisponible (navigateur, politique d'autoplay) : l'alarme visuelle suffit.
  }
}

function HeadlineKpi({ label, value, color, emphasis = false }) {
  return (
    <div
      className="flex-1 min-w-[140px] lg:min-w-0 flex flex-col justify-center px-4 py-2 lg:py-0 border-l"
      style={{ borderColor: "var(--border)" }}
      title={helpFor(label)}
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
  // Alerte SONORE facultative (AM-21) : désactivée par défaut — les
  // navigateurs n'autorisent le son qu'après un geste de l'utilisateur, et
  // une salle peut préférer le silence. Le choix est mémorisé sur le poste.
  const [sound, setSound] = useState(() => {
    try {
      return localStorage.getItem("noc-wall-sound") === "on";
    } catch {
      return false;
    }
  });
  const soundRef = useRef(sound);
  soundRef.current = sound;
  const toggleSound = () => {
    const next = !sound;
    setSound(next);
    try {
      localStorage.setItem("noc-wall-sound", next ? "on" : "off");
    } catch {
      // Stockage indisponible : le choix vaut pour cette session.
    }
    if (next) beep();
  };
  const [tick, setView] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setView((index) => index + 1), ROTATION_MS);
    return () => clearInterval(timer);
  }, []);
  const previousCritical = useRef(null);
  const critical = incidents.data?.by_severity?.critical;
  useEffect(() => {
    if (critical == null) return undefined;
    const before = previousCritical.current;
    previousCritical.current = critical;
    if (before == null || critical <= before) return undefined;
    setAlarm(true);
    if (soundRef.current) beep();
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
  // Lecture en échec, ou iTop jamais lu : « 0 incident » serait une fausse
  // bonne nouvelle. Le mur dit alors qu'il ne sait pas.
  const unknown = !d || !d.itop_collected_at;
  // Sans incidents lisibles, leur carte serait verte partout : retirée.
  const views = unknown ? MAP_VIEWS.filter((item) => item.metric !== "incidents") : MAP_VIEWS;
  const view = tick % views.length;
  const count = (value) => (unknown ? "—" : num(value, "0"));
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
      // Écran étroit : les blocs s'empilent et la page défile ; à partir de
      // 1 024 px, la disposition fixe du mur (rien ne défile).
      className={`wallboard fixed inset-0 z-50 flex flex-col overflow-y-auto lg:overflow-hidden ${alarm ? "wall-alarm" : ""}`}
      style={{ background: "var(--page)" }}
    >
      {/* --- Bandeau : identité, chiffres clés, heure --- */}
      <header
        className="flex flex-wrap lg:flex-nowrap items-stretch border-b shrink-0"
        style={{ minHeight: 88, borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <div className="flex flex-col justify-center px-4 py-2 lg:py-0 shrink-0">
          <div className="flex items-center gap-2.5">
            <span className="live-dot" style={{ width: 10, height: 10 }} />
            <h1 className="text-[24px] font-semibold tracking-tight">NOC RESINA</h1>
          </div>
          <span className="text-[13px]" style={{ color: "var(--ink-3)" }}>
            Incidents iTop · tout le réseau
          </span>
        </div>

        <HeadlineKpi label="Incidents ouverts" value={count(d?.total)} />
        <HeadlineKpi
          label="SLA dépassé"
          value={count(d?.sla_breached)}
          color={unknown ? undefined : d?.sla_breached ? "var(--sev-critical)" : "var(--state-up)"}
        />
        <HeadlineKpi
          label="Non affectés"
          value={count(d?.unassigned)}
          color={unknown ? undefined : d?.unassigned ? "var(--sev-high)" : "var(--state-up)"}
        />
        <HeadlineKpi
          label="Nouveaux (1 h)"
          value={count(d?.opened_last_hour)}
          color={d?.opened_last_hour ? "var(--sev-medium)" : undefined}
        />
        <HeadlineKpi
          label="Parc en service"
          value={availabilityPct(network.data?.availability_pct, 1)}
          color={fleetColor(network.data?.availability_pct)}
        />

        <div className="flex flex-wrap lg:flex-nowrap items-center gap-3 pl-4 pr-3 py-2 lg:py-0 border-l min-w-0 lg:shrink-0 ml-auto" style={{ borderColor: "var(--border)" }}>
          <div className="flex flex-col items-end">
            <time className="num text-[30px] leading-none tracking-tight">
              {now.toLocaleTimeString("fr-FR", { timeZone: "Africa/Ouagadougou", hour12: false })}
            </time>
            <span className="text-[13px] capitalize mt-1" style={{ color: "var(--ink-3)" }}>
              {now.toLocaleDateString("fr-FR", { timeZone: "Africa/Ouagadougou", weekday: "long", day: "numeric", month: "long" })}
            </span>
          </div>
          <span
            className="text-[12px] flex items-center gap-1.5"
            style={{ color: live ? "var(--state-up)" : "var(--sev-medium)" }}
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
            {live ? "direct" : "différé"}
          </span>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={toggleSound}
            aria-pressed={sound}
            title={sound ? "Couper l'alerte sonore des nouveaux critiques" : "Activer l'alerte sonore des nouveaux critiques"}
          >
            {sound ? <Volume2 size={16} /> : <VolumeX size={16} />}
          </button>
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

      <div className="lg:flex-1 lg:min-h-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-12 gap-3 p-3">
        {/* --- Gravité des incidents --- */}
        <div className="sm:col-span-2 lg:col-span-2 grid grid-cols-2 sm:grid-cols-4 lg:flex lg:flex-col gap-3 min-h-0">
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
                  {count(value)}
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
        <div className="sm:col-span-2 lg:col-span-7 panel min-h-[320px] lg:min-h-0 flex flex-col">
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
                {unknown && !incidents.isPending && (
                  <tr>
                    <td className="text-center" style={{ height: 160, color: "var(--sev-high)" }}>
                      <span style={{ fontSize: 24 }}>Incidents iTop indisponibles</span>
                    </td>
                  </tr>
                )}
                {!unknown && d.incidents.length === 0 && (
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
        <div className="sm:col-span-2 lg:col-span-3 flex flex-col gap-3 min-h-0">
          <div className="panel overflow-hidden shrink-0">
            <header className="panel-head">
              <h2 className="panel-title">{views[view].label}</h2>
              <span className="ml-auto flex gap-1" aria-hidden="true">
                {views.map((item, index) => (
                  <span
                    key={item.metric}
                    className="dot"
                    style={{ background: index === view ? "var(--accent)" : "var(--border-strong)" }}
                  />
                ))}
              </span>
            </header>
            <TerritoryMap
              key={views[view].metric}
              level="region"
              rows={geo.data?.rows}
              height={250}
              defaultMetric={views[view].metric}
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
        {!unknown && (incidents.isError || d.itop_stale) && (
          <span style={{ color: "var(--sev-critical)" }}>
            iTop ne répond plus : dernière lecture il y a {ageFrom(d.itop_collected_at)}
          </span>
        )}
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

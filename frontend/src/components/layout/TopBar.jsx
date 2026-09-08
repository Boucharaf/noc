import {
  ChevronLeft,
  ChevronRight,
  LogOut,
  Monitor,
  Moon,
  PanelLeft,
  Pause,
  Play,
  Sun,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import StatusStrip from "./StatusStrip";
import { ROLE_LABEL } from "../../lib/permissions";
import { auth } from "../../api/noc";
import { useAuthStore } from "../../store/auth";
import { useClock } from "../../hooks/useClock";
import { useUiStore } from "../../store/ui";

/**
 * Barre supérieure — le « fronton » de la salle.
 *
 * Contient dans l'ordre de lecture (gauche → droite) :
 *   identité du système · compteurs d'alerte · santé de la collecte ·
 *   état du flux temps réel · horloge · préférences · compte.
 *
 * L'horloge et le point « live » sont volontairement les derniers
 * éléments avant le compte : ce sont les deux témoins que l'écran n'est
 * pas figé. Un tableau de bord gelé sur des chiffres anciens est le pire
 * mode de panne d'un NOC, parce qu'il ne se signale pas tout seul.
 */

const REALTIME_STATE = {
  live: { label: "Temps réel", color: "var(--state-up)" },
  connecting: { label: "Connexion…", color: "var(--sev-medium)" },
  offline: { label: "Flux coupé", color: "var(--sev-critical)" },
};

export default function TopBar({ realtimeStatus, health, toolsHealthy, toolsTotal, canSeeIncidents }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const now = useClock();

  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const toggleRail = useUiStore((s) => s.toggleRail);
  const autoRefresh = useUiStore((s) => s.autoRefresh);
  const setAutoRefresh = useUiStore((s) => s.setAutoRefresh);

  const realtime = REALTIME_STATE[realtimeStatus] ?? REALTIME_STATE.connecting;

  const healthColor =
    health?.status === "ok"
      ? "var(--state-up)"
      : health?.status === "degraded"
        ? "var(--sev-medium)"
        : "var(--sev-critical)";

  const handleLogout = async () => {
    try {
      await auth.logout();
    } catch {
      // Le cookie a pu déjà expirer côté serveur : on nettoie l'état
      // local dans tous les cas, sinon l'utilisateur reste bloqué sur une
      // session morte.
    }
    logout();
    navigate("/connexion", { replace: true });
  };

  return (
    <header
      className="shrink-0 flex items-center gap-3 px-2.5 border-b"
      style={{
        height: "var(--topbar-h)",
        borderColor: "var(--border)",
        background: "var(--surface)",
      }}
    >
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        onClick={toggleRail}
        aria-label="Replier la navigation"
        title="Replier / déplier la navigation"
      >
        <PanelLeft size={14} />
      </button>

      <Link
        to="/"
        className="flex items-center gap-2 shrink-0"
        style={{ textDecoration: "none", color: "inherit" }}
      >
        <span
          className="dot"
          style={{ background: healthColor, width: 9, height: 9 }}
          title={
            health
              ? `Backend : ${health.status} · base ${health.checks?.database?.status ?? "?"} · Redis ${
                  health.checks?.redis?.status ?? "?"
                }`
              : "État du backend inconnu"
          }
        />
        <span className="font-semibold tracking-tight text-[13.5px] whitespace-nowrap">
          NOC RESINA
        </span>
      </Link>

      <div
        className="h-5 border-l shrink-0"
        style={{ borderColor: "var(--border)" }}
        aria-hidden="true"
      />

      <div className="min-w-0 flex-1 overflow-hidden">
        <StatusStrip canSeeIncidents={canSeeIncidents} />
      </div>

      {/* Fraîcheur de la collecte : un backend en bonne santé qui ne
          reçoit plus rien depuis 2 h affiche des données mortes. */}
      {toolsTotal > 0 && (
        <Link
          to="/integrations"
          className="hidden lg:flex items-center gap-1.5 shrink-0 text-[10.5px]"
          style={{ textDecoration: "none", color: "var(--ink-3)" }}
          title="Collecteurs ETL actifs sur le total configuré"
        >
          <span
            className="dot"
            style={{
              background:
                toolsHealthy === 0
                  ? "var(--sev-critical)"
                  : toolsHealthy < toolsTotal
                    ? "var(--sev-medium)"
                    : "var(--state-up)",
            }}
          />
          <span className="num">
            {toolsHealthy}/{toolsTotal}
          </span>
          collecte
        </Link>
      )}

      <span
        className="hidden md:flex items-center gap-1.5 shrink-0 text-[10.5px]"
        style={{ color: "var(--ink-3)" }}
        title={`Flux WebSocket : ${realtime.label}`}
      >
        {realtimeStatus === "live" ? (
          <span className="live-dot" style={{ background: realtime.color }} />
        ) : (
          <span className="dot" style={{ background: realtime.color }} />
        )}
        {realtime.label}
      </span>

      <time
        className="num shrink-0 text-[13px] tracking-tight"
        dateTime={now.toISOString()}
        title={now.toLocaleDateString("fr-FR", { dateStyle: "full" })}
      >
        {now.toLocaleTimeString("fr-FR", { hour12: false })}
      </time>

      <div className="flex items-center gap-0.5 shrink-0">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setAutoRefresh(!autoRefresh)}
          title={
            autoRefresh
              ? "Rafraîchissement automatique actif — cliquer pour figer l'écran"
              : "Écran figé — cliquer pour reprendre le rafraîchissement"
          }
          aria-pressed={autoRefresh}
        >
          {autoRefresh ? <Pause size={13} /> : <Play size={13} style={{ color: "var(--sev-medium)" }} />}
        </button>
        <Link to="/mur" className="btn btn-ghost btn-sm" title="Mode mur d'écrans (plein écran)">
          <Monitor size={13} />
        </Link>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={toggleTheme}
          title={theme === "dark" ? "Passer en thème clair" : "Passer en thème sombre"}
        >
          {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
        </button>
      </div>

      <div
        className="flex items-center gap-2 pl-2.5 border-l shrink-0"
        style={{ borderColor: "var(--border)" }}
      >
        <Link to="/compte" className="text-right leading-tight" style={{ textDecoration: "none" }}>
          <div className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
            {user?.full_name || user?.username}
          </div>
          <div className="text-[10px]" style={{ color: "var(--ink-3)" }}>
            {ROLE_LABEL[user?.role] ?? user?.role}
          </div>
        </Link>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={handleLogout}
          title="Se déconnecter"
          // Bouton sans texte : sans aria-label, un lecteur d'écran
          // n'annonce rien du tout et le contrôle est inatteignable au
          // clavier assisté.
          aria-label="Se déconnecter"
        >
          <LogOut size={13} />
        </button>
      </div>
    </header>
  );
}

/** Fil d'Ariane + navigation période, réutilisé en tête de chaque page. */
export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <div className="flex items-start gap-3 flex-wrap mb-2">
      <div className="min-w-0">
        <h1 className="text-[15px] font-semibold leading-tight tracking-tight">{title}</h1>
        {subtitle && (
          <p className="text-[11.5px] mt-0.5" style={{ color: "var(--ink-3)" }}>
            {subtitle}
          </p>
        )}
      </div>
      {children}
      {actions && <div className="ml-auto flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

/** Sélecteur de mois — utilisé par tous les écrans analytiques. */
export function PeriodPicker({ label, onPrevious, onNext, onCurrent, isCurrent }) {
  return (
    <div className="flex items-center gap-1">
      <button type="button" className="btn btn-sm" onClick={onPrevious} aria-label="Mois précédent">
        <ChevronLeft size={13} />
      </button>
      <span
        className="text-[12px] font-medium px-1.5 min-w-[104px] text-center capitalize"
        title={`Période analysée : ${label}`}
      >
        {label}
      </span>
      <button
        type="button"
        className="btn btn-sm"
        onClick={onNext}
        disabled={isCurrent}
        aria-label="Mois suivant"
        title={isCurrent ? "Le mois en cours est le plus récent disponible" : "Mois suivant"}
      >
        <ChevronRight size={13} />
      </button>
      {!isCurrent && (
        <button type="button" className="btn btn-sm" onClick={onCurrent}>
          Mois en cours
        </button>
      )}
    </div>
  );
}

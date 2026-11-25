import {
  ChevronLeft,
  ChevronRight,
  LogOut,
  BookOpen,
  Menu,
  Monitor,
  Moon,
  PanelLeft,
  Sun,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { PERMISSIONS, ROLE_LABEL, hasPermission } from "../../lib/permissions";
import { auth } from "../../api/noc";
import { useAuthStore } from "../../store/auth";
import { useClock } from "../../hooks/useClock";
import LegendModal from "./LegendModal";
import { useUiStore } from "../../store/ui";
import { ConfirmModal } from "../ui/Overlay";
import { useSourceHealth } from "../../hooks/queries";
import { isFailing, sourcesSentence } from "../../lib/sources";

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
  // Sans flux, les écrans continuent de relire l'API : le dire.
  offline: { label: "Différé", color: "var(--sev-medium)" },
};

export default function TopBar({ realtimeStatus, health, toolsHealthy, toolsTotal, onMenu }) {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const now = useClock();
  const [logoutOpen, setLogoutOpen] = useState(false);
  const [legendOpen, setLegendOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const theme = useUiStore((s) => s.theme);
  const toggleTheme = useUiStore((s) => s.toggleTheme);
  const toggleRail = useUiStore((s) => s.toggleRail);

  const realtime = REALTIME_STATE[realtimeStatus] ?? REALTIME_STATE.connecting;
  const sources = useSourceHealth();
  const failingSources = (sources.data?.tools ?? []).filter(isFailing);

  const healthColor =
    health?.status === "ok"
      ? "var(--state-up)"
      : health?.status === "degraded"
        ? "var(--sev-medium)"
        : "var(--sev-critical)";

  const handleLogout = async () => {
    setLoggingOut(true);
    try {
      await auth.logout();
    } catch {
      // Le cookie a pu déjà expirer côté serveur : on nettoie l'état
      // local dans tous les cas, sinon l'utilisateur reste bloqué sur une
      // session morte.
    }
    logout();
    navigate("/connexion", { replace: true });
    setLoggingOut(false);
  };

  return (
    <header
      className="app-header shrink-0 flex items-center gap-3 px-4 border-b"
      style={{
        height: "var(--topbar-h)",
        borderColor: "var(--border)",
        background: "var(--topbar-bg, var(--surface))",
      }}
    >
      {/* Téléphone : ouvre le tiroir de navigation. Au-delà : replie le rail.
          (Enveloppés : la règle .btn l'emporterait sur `hidden`.) */}
      <span className="md:hidden">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onMenu}
          aria-label="Ouvrir le menu"
          title="Menu"
        >
          <Menu size={16} />
        </button>
      </span>
      <span className="hidden md:inline-flex">
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={toggleRail}
          aria-label="Replier la navigation"
          title="Replier / déplier la navigation"
        >
          <PanelLeft size={14} />
        </button>
      </span>

      {/* Le logo est dans la barre latérale (maquette) ; sur téléphone, où
          elle est repliée dans un tiroir, il reste ici. */}
      <Link
        to="/"
        className="flex items-center gap-2 shrink-0"
        style={{ textDecoration: "none", color: "inherit" }}
      >
        <span
          className="dot"
          style={{ background: healthColor, width: 9, height: 9 }}
          title={
            !health
              ? "État de la plateforme inconnu"
              : health.status === "ok"
                ? "Plateforme opérationnelle"
                : "Plateforme perturbée"
          }
        />
        <img
          src="/images.png"
          alt="ANPTIC"
          className="block md:hidden"
          style={{ height: 30, width: "auto", objectFit: "contain" }}
        />
        <span
          className="hidden md:inline text-[14px] font-semibold"
          style={{ fontFamily: "var(--font-display)", color: "var(--ink)" }}
        >
          Centre des opérations réseau
        </span>
      </Link>

      {/* Plus de compteurs d'alertes ni d'incidents dans l'en-tête : ils sont
          sur chaque tableau de bord, filtrés par le périmètre choisi. L'espace
          porte l'accès au mur d'écrans, le raccourci de l'exploitant pressé. */}
      <div className="flex-1 sm:hidden" />
      <div className="min-w-0 flex-1 hidden sm:flex items-center justify-center">
        {hasPermission(user?.role, PERMISSIONS.VIEW_INCIDENTS) && <Link
          to="/mur"
          className="btn btn-sm shrink-0"
          style={{
            gap: 8,
            paddingInline: 14,
            color: "var(--accent-ink)",
            borderColor: "color-mix(in srgb, var(--accent) 55%, transparent)",
            background: "color-mix(in srgb, var(--accent) 12%, var(--surface))",
            fontWeight: 600,
          }}
          title="Mode mur d'écrans : le résumé des incidents iTop, en plein écran"
        >
          <Monitor size={14} />
          <span className="hidden lg:inline">Mode mur d'écran</span>
          <span className="hidden 2xl:inline text-[12px] font-normal" style={{ color: "var(--ink-3)" }}>
            résumé des incidents · plein écran
          </span>
        </Link>}
      </div>

      {/* Fraîcheur de la collecte : un backend en bonne santé qui ne
          reçoit plus rien depuis 2 h affiche des données mortes. */}
      {/* INC-32 : toujours visible (y compris menu replié et écran étroit),
          avec la liste des sources en erreur au survol. */}
      {toolsTotal > 0 && (
        <Link
          to="/integrations"
          className="flex items-center gap-1.5 shrink-0 text-[12px]"
          style={{ textDecoration: "none", color: failingSources.length ? "var(--sev-medium)" : "var(--ink-3)" }}
          title={
            sourcesSentence(sources.data?.tools) ??
            `${toolsHealthy}/${toolsTotal} outils de supervision actifs — collecte complète`
          }
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
          <span className="hidden sm:inline">collecte</span>
        </Link>
      )}

      <span
        className="hidden lg:flex items-center gap-1.5 shrink-0 text-[12px]"
        style={{ color: "var(--ink-3)" }}
        title={
          realtimeStatus === "offline"
            ? "Flux temps réel coupé : les écrans se mettent à jour toutes les 20 à 60 s. Reconnexion automatique."
            : `Mise à jour en direct : ${realtime.label}`
        }
      >
        {realtimeStatus === "live" ? (
          <span className="live-dot" style={{ background: realtime.color }} />
        ) : (
          <span className="dot" style={{ background: realtime.color }} />
        )}
        {realtime.label}
      </span>

      <time
        className="num shrink-0 text-[15px] font-semibold tracking-tight px-2.5 py-1 rounded-full border"
        style={{ borderColor: "var(--border)", background: "var(--surface-2)", fontFamily: "var(--font-display)" }}
        dateTime={now.toISOString()}
        title={now.toLocaleDateString("fr-FR", { timeZone: "Africa/Ouagadougou", dateStyle: "full" })}
      >
        {now.toLocaleTimeString("fr-FR", { timeZone: "Africa/Ouagadougou", hour12: false })}
        {/* INC-14 : le fuseau est affiché (Burkina Faso : GMT, sans heure d'été). */}
        <span className="hidden sm:inline text-[12px] ml-1" style={{ color: "var(--ink-3)" }}>GMT</span>
      </time>

      <div className="flex items-center gap-0.5 shrink-0">
        <span className="hidden sm:inline-flex">
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => setLegendOpen(true)}
            title="Légende : couleurs, états et vocabulaire du NOC"
          >
            <BookOpen size={13} />
            <span className="hidden xl:inline text-[12px]">Légende</span>
          </button>
        </span>
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
        className="flex items-center gap-2 pl-1.5 sm:pl-2.5 border-l shrink-0"
        style={{ borderColor: "var(--border)" }}
      >
        {/* Nom et rôle à partir de la tablette ; sur téléphone, « Mon compte »
            est dans le menu. */}
        <Link to="/compte" className="hidden lg:block text-right leading-tight" style={{ textDecoration: "none" }}>
          <div className="text-[12px] font-medium" style={{ color: "var(--ink)" }}>
            {user?.full_name || user?.username}
          </div>
          <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
            {ROLE_LABEL[user?.role] ?? user?.role}
          </div>
        </Link>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={() => setLogoutOpen(true)}
          title="Se déconnecter"
          // Bouton sans texte : sans aria-label, un lecteur d'écran
          // n'annonce rien du tout et le contrôle est inatteignable au
          // clavier assisté.
          aria-label="Se déconnecter"
        >
          <LogOut size={13} />
        </button>
      </div>
      <ConfirmModal
        open={logoutOpen}
        onClose={() => setLogoutOpen(false)}
        onConfirm={handleLogout}
        title="Confirmer la déconnexion"
        pending={loggingOut}
      >
        <p className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
          Voulez-vous vraiment vous déconnecter de cette session ?
        </p>
      </ConfirmModal>
      <LegendModal open={legendOpen} onClose={() => setLegendOpen(false)} />
    </header>
  );
}

/** Fil d'Ariane + navigation période, réutilisé en tête de chaque page. */
export function PageHeader({ title, subtitle, actions, children }) {
  return (
    <div className="flex items-end gap-3 flex-wrap mb-3">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle">{subtitle}</p>}
      </div>
      {children}
      {actions && <div className="ml-auto flex max-w-full items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  );
}

/** Sélecteur de mois — utilisé par tous les écrans analytiques. */
export function PeriodPicker({ label, onPrevious, onNext, onCurrent, isCurrent }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
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

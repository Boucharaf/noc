import { AlertTriangle, Inbox, Loader2, ShieldOff, WifiOff } from "lucide-react";

import { errorMessage } from "../../api/client";

/**
 * États non nominaux d'un panneau : vide, en chargement, en erreur.
 *
 * Trois messages distincts, jamais confondus — c'est le point le plus
 * important de ce fichier. « Aucun incident critique » et « impossible de
 * joindre le backend » produisent tous deux un tableau vide, et un NOC qui
 * affiche le premier alors qu'il faut lire le second ne voit pas une
 * panne majeure. Chaque état a donc son icône, son ton et son message.
 */

export function EmptyState({ message = "Aucune donnée", hint, icon: Icon = Inbox, compact = false }) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-center gap-1.5 ${
        compact ? "py-5" : "py-10"
      }`}
      style={{ color: "var(--ink-3)" }}
    >
      <Icon size={compact ? 16 : 20} strokeWidth={1.6} />
      <p className="text-[12.5px]">{message}</p>
      {hint && <p className="text-[11px] max-w-[42ch] leading-snug">{hint}</p>}
    </div>
  );
}

export function LoadingState({ label = "Chargement…", compact = false }) {
  return (
    <div
      className={`flex items-center justify-center gap-2 ${compact ? "py-5" : "py-10"}`}
      style={{ color: "var(--ink-3)" }}
    >
      <Loader2 size={14} className="animate-spin" />
      <span className="text-[12px]">{label}</span>
    </div>
  );
}

/**
 * Erreur de chargement.
 *
 * Distingue explicitement le 403 (droits insuffisants — normal, pas une
 * panne) de la coupure réseau et de l'erreur serveur : l'utilisateur ne
 * doit pas alerter l'astreinte parce qu'un écran lui est simplement
 * interdit.
 */
export function ErrorState({ error, onRetry, compact = false }) {
  const forbidden = error?.isForbidden || error?.response?.status === 403;
  const offline = error?.isNetworkError;

  const Icon = forbidden ? ShieldOff : offline ? WifiOff : AlertTriangle;
  const color = forbidden ? "var(--ink-3)" : "var(--sev-high)";
  const title = forbidden
    ? "Accès non autorisé"
    : offline
      ? "Backend injoignable"
      : "Échec du chargement";

  return (
    <div
      className={`flex flex-col items-center justify-center text-center gap-1.5 ${
        compact ? "py-5" : "py-10"
      }`}
      style={{ color }}
    >
      <Icon size={compact ? 16 : 20} strokeWidth={1.6} />
      <p className="text-[12.5px] font-medium">{title}</p>
      <p className="text-[11px] max-w-[46ch] leading-snug" style={{ color: "var(--ink-3)" }}>
        {forbidden
          ? "Votre profil ne donne pas accès à cette information."
          : errorMessage(error)}
      </p>
      {onRetry && !forbidden && (
        <button type="button" className="btn btn-sm mt-1.5" onClick={onRetry}>
          Réessayer
        </button>
      )}
    </div>
  );
}

/** Lignes fantômes calquées sur la hauteur réelle d'une ligne (28 px). */
export function SkeletonRows({ rows = 6, columns = 4 }) {
  return (
    <div className="p-2 space-y-1.5">
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-2">
          {Array.from({ length: columns }).map((_, colIndex) => (
            <div
              key={colIndex}
              className="skeleton h-[18px]"
              style={{ flex: colIndex === 0 ? 2 : 1 }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonBlock({ height = 120 }) {
  return <div className="skeleton w-full" style={{ height }} />;
}

/**
 * Enveloppe standard d'un panneau alimenté par une requête.
 * Évite de réécrire la même cascade if(isLoading)/if(error)/if(empty)
 * dans quarante composants — et donc d'en oublier une.
 */
export function QueryBoundary({
  query,
  children,
  empty,
  emptyMessage = "Aucune donnée",
  emptyHint,
  emptyIcon,
  skeleton,
  compact = false,
}) {
  if (query.isLoading) {
    return skeleton ?? <LoadingState compact={compact} />;
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={query.refetch} compact={compact} />;
  }
  const isEmpty =
    typeof empty === "function"
      ? empty(query.data)
      : Array.isArray(query.data)
        ? query.data.length === 0
        : query.data === null || query.data === undefined;

  if (isEmpty) {
    return (
      <EmptyState
        message={emptyMessage}
        hint={emptyHint}
        icon={emptyIcon}
        compact={compact}
      />
    );
  }
  return typeof children === "function" ? children(query.data) : children;
}

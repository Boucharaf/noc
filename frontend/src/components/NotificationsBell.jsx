import React, { useMemo, useState } from "react";
import { Bell, BellOff, BellRing, Check } from "lucide-react";
import { useAcknowledgeIncident, useRecentNotifications } from "../hooks/useRealtime";
import { usePushNotifications } from "../hooks/usePushNotifications";
import { useAuthStore } from "../store/auth";
import { SEVERITY_COLOR } from "../theme/colors";

const LAST_SEEN_KEY = "noc-notifications-last-seen";

const formatAge = (minutes) => {
  if (minutes == null) return "—";
  if (minutes < 60) return `il y a ${minutes} min`;
  if (minutes < 1440) return `il y a ${Math.round(minutes / 60)}h`;
  return `il y a ${Math.round(minutes / 1440)}j`;
};

// The bell is a dropdown of recent critical/high incidents (what actually
// triggers SMS/email/push), not just a push on/off switch — subscribing to
// push moves into the footer so the bell's primary action is "show me what
// happened" rather than a permission prompt.
const NotificationsBell = () => {
  const { data: notifications = [] } = useRecentNotifications(10);
  const acknowledge = useAcknowledgeIncident();
  const push = usePushNotifications();
  const role = useAuthStore((state) => state.user?.role);
  const canAcknowledge = role === "admin" || role === "noc_agent";

  const [open, setOpen] = useState(false);
  const [lastSeen, setLastSeen] = useState(() => localStorage.getItem(LAST_SEEN_KEY) || "");

  const unreadCount = useMemo(() => {
    if (!lastSeen) return notifications.length;
    const lastSeenDate = new Date(lastSeen);
    return notifications.filter((n) => new Date(n.detected_at) > lastSeenDate).length;
  }, [notifications, lastSeen]);

  const handleToggleOpen = () => {
    setOpen((wasOpen) => {
      if (!wasOpen) {
        const now = new Date().toISOString();
        localStorage.setItem(LAST_SEEN_KEY, now);
        setLastSeen(now);
      }
      return !wasOpen;
    });
  };

  return (
    <div className="relative">
      <button
        onClick={handleToggleOpen}
        className="relative rounded-lg border p-2 transition-colors hover:bg-[var(--color-surface-2)]"
        style={{ borderColor: "var(--color-border)" }}
        aria-label="Notifications"
        title="Notifications"
      >
        <Bell className="h-4 w-4" />
        {unreadCount > 0 && (
          <span
            className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-bold text-white"
            style={{ background: "var(--color-critical, #d03b3b)" }}
          >
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 z-40 mt-2 w-80 rounded-lg border text-sm"
            style={{
              background: "var(--color-surface)",
              borderColor: "var(--color-border-strong)",
              boxShadow: "var(--shadow-elevate)",
            }}
          >
            <div
              className="border-b px-3 py-2"
              style={{ borderColor: "var(--color-border)" }}
            >
              <p
                className="text-xs font-semibold uppercase tracking-wide"
                style={{ color: "var(--color-text-secondary)" }}
              >
                Notifications récentes
              </p>
            </div>

            <div className="max-h-80 overflow-y-auto">
              {notifications.length === 0 && (
                <p
                  className="p-4 text-center text-sm"
                  style={{ color: "var(--color-text-muted)" }}
                >
                  Aucune notification récente.
                </p>
              )}
              {notifications.map((n) => {
                const color = SEVERITY_COLOR[n.severity] ?? SEVERITY_COLOR.low;
                return (
                  <div
                    key={n.id}
                    className="flex items-start gap-3 border-b px-3 py-2.5 last:border-0"
                    style={{ borderColor: "var(--color-border)" }}
                  >
                    <div className="min-w-0 flex-1">
                      <p
                        className="truncate text-sm font-medium"
                        style={{ color: "var(--color-text-primary)" }}
                      >
                        <span className="font-mono text-xs" style={{ color }}>
                          [{n.node_code}]
                        </span>{" "}
                        {n.description ?? "Incident sans description"}
                      </p>
                      <p
                        className="text-xs"
                        style={{ color: "var(--color-text-secondary)" }}
                      >
                        {n.locality} — {formatAge(n.age_minutes)}
                        {n.itop_ticket_id && (
                          <span
                            className="ml-2 font-mono"
                            style={{ color: "var(--color-accent)" }}
                          >
                            {n.itop_ticket_id}
                          </span>
                        )}
                      </p>
                    </div>
                    {canAcknowledge && n.status === "open" && (
                      <button
                        onClick={() => acknowledge.mutate(n.id)}
                        disabled={acknowledge.isPending}
                        title="Prendre en charge"
                        className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-[var(--color-surface-3)]"
                        style={{ color: "var(--color-text-muted)" }}
                      >
                        <Check className="h-4 w-4" />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            {push.supported && (
              <div
                className="flex items-center justify-between gap-2 border-t px-3 py-2.5"
                style={{ borderColor: "var(--color-border)" }}
              >
                <span
                  className="text-xs"
                  style={{
                    color: push.error
                      ? "var(--color-critical, #d03b3b)"
                      : "var(--color-text-secondary)",
                  }}
                >
                  {push.error
                    ? `Erreur : ${push.error}`
                    : push.permission === "denied"
                      ? "Notifications push bloquées par le navigateur"
                      : "Notifications push (incidents critiques)"}
                </span>
                <button
                  onClick={push.toggle}
                  disabled={push.loading || push.permission === "denied"}
                  className="shrink-0 rounded-md p-1.5 transition-colors hover:bg-[var(--color-surface-3)] disabled:opacity-50"
                  style={{ color: push.subscribed ? "var(--color-accent)" : "var(--color-text-muted)" }}
                  aria-label="Activer/désactiver les notifications push"
                  title={
                    push.subscribed
                      ? "Désactiver les notifications push"
                      : "Activer les notifications push"
                  }
                >
                  {push.permission === "denied" ? (
                    <BellOff className="h-4 w-4" />
                  ) : push.subscribed ? (
                    <BellRing className="h-4 w-4" />
                  ) : (
                    <Bell className="h-4 w-4" />
                  )}
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default NotificationsBell;

import { useState } from "react";
import { Bell, BellOff, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";

import Panel from "../components/ui/Panel";
import { Field, Notice, Segmented } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { Badge } from "../components/ui/Badge";
import { DefRow } from "../components/ui/Stat";
import { ROLE_DESCRIPTION, ROLE_LABEL } from "../lib/permissions";
import { auth, notifications } from "../api/noc";
import { dateTime } from "../lib/format";
import { errorMessage } from "../api/client";
import { useAuthStore } from "../store/auth";
import { useCurrentUser } from "../hooks/useSession";
import { useUiStore } from "../store/ui";

/**
 * Compte et préférences.
 *
 * Les préférences ne sont pas de la décoration : le thème et le
 * rafraîchissement automatique changent la façon dont l'écran se comporte
 * pendant huit heures. Elles sont donc regroupées ici plutôt que cachées
 * dans un menu, et persistées par poste (localStorage).
 *
 * L'abonnement aux notifications navigateur est le seul canal qui
 * fonctionne quand l'onglet n'est pas au premier plan — c'est ce qui
 * permet de quitter la salle sans manquer une alerte critique.
 */
export default function AccountPage() {
  const user = useCurrentUser();
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const autoRefresh = useUiStore((s) => s.autoRefresh);
  const setAutoRefresh = useUiStore((s) => s.setAutoRefresh);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [feedback, setFeedback] = useState(null);
  const [pending, setPending] = useState(false);

  const [pushState, setPushState] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );
  const [pushError, setPushError] = useState(null);

  const changePassword = async (event) => {
    event.preventDefault();
    setFeedback(null);
    if (newPassword !== confirmation) {
      setFeedback({ tone: "error", message: "Les deux saisies ne correspondent pas." });
      return;
    }
    setPending(true);
    try {
      await auth.changePassword(currentPassword, newPassword);
      setFeedback({ tone: "success", message: "Mot de passe modifié." });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
    } catch (error) {
      setFeedback({ tone: "error", message: errorMessage(error) });
    } finally {
      setPending(false);
    }
  };

  const enablePush = async () => {
    setPushError(null);
    try {
      if (typeof Notification === "undefined" || !("serviceWorker" in navigator)) {
        setPushError("Ce navigateur ne prend pas en charge les notifications.");
        return;
      }
      const permission = await Notification.requestPermission();
      setPushState(permission);
      if (permission !== "granted") return;

      const { public_key: publicKey } = await notifications.vapidKey();
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      const json = subscription.toJSON();
      await notifications.subscribe({
        endpoint: json.endpoint,
        keys: { p256dh: json.keys.p256dh, auth: json.keys.auth },
      });
      setFeedback({ tone: "success", message: "Notifications activées sur ce poste." });
    } catch (error) {
      // Le cas le plus fréquent est un backend sans clés VAPID : le
      // message du serveur le dit explicitement, on le relaie tel quel.
      setPushError(errorMessage(error));
    }
  };

  const handleLogout = async () => {
    try {
      await auth.logout();
    } catch {
      /* session déjà expirée côté serveur */
    }
    logout();
    navigate("/connexion", { replace: true });
  };

  return (
    <div className="space-y-2.5" style={{ maxWidth: 900 }}>
      <PageHeader title="Mon compte" subtitle="Identité, sécurité et préférences d'affichage" />

      {feedback && (
        <Notice tone={feedback.tone} onClose={() => setFeedback(null)}>
          {feedback.message}
        </Notice>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
        <Panel title="Identité">
          <DefRow label="Nom">{user?.full_name || "—"}</DefRow>
          <DefRow label="Identifiant" mono>
            {user?.username}
          </DefRow>
          <DefRow label="Rôle">
            <Badge color="var(--accent-ink)">{ROLE_LABEL[user?.role] ?? user?.role}</Badge>
            <span className="block text-[11px] mt-1" style={{ color: "var(--ink-3)" }}>
              {ROLE_DESCRIPTION[user?.role]}
            </span>
          </DefRow>
          <DefRow label="Équipe">{user?.team || "—"}</DefRow>
          <DefRow label="Téléphone" mono>
            {user?.phone_number || "—"}
          </DefRow>
          <DefRow label="Matricule" mono>
            {user?.employee_code || "—"}
          </DefRow>
          <DefRow label="Dernière connexion" mono>
            {user?.last_login_at ? dateTime(user.last_login_at) : "—"}
          </DefRow>

          <div className="mt-3 pt-2.5 border-t" style={{ borderColor: "var(--border)" }}>
            <button type="button" className="btn btn-sm" onClick={handleLogout}>
              <LogOut size={13} /> Se déconnecter
            </button>
          </div>
        </Panel>

        <Panel title="Mot de passe">
          <form onSubmit={changePassword} className="space-y-2.5">
            <Field label="Mot de passe actuel" required>
              <input
                className="input"
                type="password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                autoComplete="current-password"
              />
            </Field>
            <Field label="Nouveau mot de passe" required hint="8 caractères minimum.">
              <input
                className="input"
                type="password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <Field
              label="Confirmation"
              required
              error={
                confirmation && confirmation !== newPassword
                  ? "Les deux saisies diffèrent."
                  : null
              }
            >
              <input
                className="input"
                type="password"
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                autoComplete="new-password"
              />
            </Field>
            <button
              type="submit"
              className="btn btn-sm btn-primary"
              disabled={
                pending ||
                !currentPassword ||
                newPassword.length < 8 ||
                newPassword !== confirmation
              }
            >
              {pending ? "…" : "Modifier"}
            </button>
          </form>
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
        <Panel title="Affichage">
          <div className="space-y-3">
            <Field
              label="Thème"
              hint="Le thème sombre est conçu pour une salle peu éclairée et une journée complète devant l'écran."
            >
              <Segmented
                ariaLabel="Thème"
                value={theme}
                onChange={setTheme}
                options={[
                  { value: "dark", label: "Sombre" },
                  { value: "light", label: "Clair" },
                ]}
              />
            </Field>

            <Field
              label="Rafraîchissement automatique"
              hint="Coupez-le sur une liaison de secours : l'écran cesse d'interroger le serveur et n'affiche plus que les données déjà chargées."
            >
              <Segmented
                ariaLabel="Rafraîchissement"
                value={autoRefresh ? "on" : "off"}
                onChange={(value) => setAutoRefresh(value === "on")}
                options={[
                  { value: "on", label: "Actif" },
                  { value: "off", label: "Figé" },
                ]}
              />
            </Field>

            <div className="flex items-center gap-2 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              {theme === "dark" ? <Moon size={13} /> : <Sun size={13} />}
              <Monitor size={13} />
              Ces préférences sont mémorisées sur ce poste uniquement.
            </div>
          </div>
        </Panel>

        <Panel title="Notifications navigateur">
          <p className="text-[12px] mb-2" style={{ color: "var(--ink-2)" }}>
            Recevez les incidents critiques même lorsque l'onglet n'est pas au premier
            plan. Le backend n'envoie que les gravités {" "}
            <strong>critique</strong> et <strong>majeure</strong>.
          </p>
          {pushError && <Notice tone="error">{pushError}</Notice>}
          <div className="flex items-center gap-2 mt-2">
            {pushState === "granted" ? (
              <span className="badge" style={{ color: "var(--state-up)", background: "color-mix(in srgb, var(--state-up) 14%, transparent)" }}>
                <Bell size={11} /> Activées
              </span>
            ) : (
              <button type="button" className="btn btn-sm" onClick={enablePush}>
                <BellOff size={13} /> Activer sur ce poste
              </button>
            )}
            {pushState === "denied" && (
              <span className="text-[11px]" style={{ color: "var(--sev-medium)" }}>
                Refusées dans les réglages du navigateur — à réautoriser depuis la barre
                d'adresse.
              </span>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

/**
 * Conversion de la clé publique VAPID (base64url) en Uint8Array.
 * `PushManager.subscribe` n'accepte pas la chaîne telle quelle, et la
 * base64url du serveur n'est pas de la base64 standard : il faut
 * restaurer le remplissage et remettre les caractères `+` et `/`.
 */
function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  return Uint8Array.from([...raw].map((char) => char.charCodeAt(0)));
}

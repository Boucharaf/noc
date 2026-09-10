import { useState } from "react";
import { Bell, BellOff, LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

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
 * Chaque utilisateur, quel que soit son rôle, modifie ici SES identifiants :
 * identifiant de connexion, nom, coordonnées, mot de passe, abonnement aux
 * alertes par courriel. Le RÔLE n'y est qu'affiché — seul un Chef NOC
 * l'attribue, depuis la gestion des comptes, et le backend refuse le champ
 * sur cette route (schemas/users.py::UserSelfUpdate).
 *
 * Les préférences d'affichage changent la façon dont l'écran se comporte
 * pendant huit heures : elles sont regroupées ici plutôt que cachées dans un
 * menu, et persistées par poste (localStorage).
 */

// Miroirs des motifs de backend/app/schemas/users.py.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;

export default function AccountPage() {
  const user = useCurrentUser();
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const autoRefresh = useUiStore((s) => s.autoRefresh);
  const setAutoRefresh = useUiStore((s) => s.setAutoRefresh);

  const [feedback, setFeedback] = useState(null);

  const [pushState, setPushState] = useState(
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );
  const [pushError, setPushError] = useState(null);

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

      const { public_key: publicKey } = await notifications.vapidPublicKey();
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

  const handleLogout = async (reason = null) => {
    try {
      await auth.logout();
    } catch {
      /* session déjà expirée côté serveur */
    }
    logout(reason);
    navigate("/connexion", { replace: true });
  };

  return (
    <div className="space-y-2.5" style={{ maxWidth: 900 }}>
      <PageHeader title="Mon compte" subtitle="Identifiants, sécurité et préférences d'affichage" />

      {feedback && (
        <Notice tone={feedback.tone} onClose={() => setFeedback(null)}>
          {feedback.message}
        </Notice>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2.5">
        {user && (
          <IdentityPanel
            // Remonté à chaque changement de compte : le formulaire repart
            // des valeurs du compte courant, jamais de celles du précédent.
            key={user.id}
            user={user}
            onSaved={(updated, message) => {
              setUser(updated);
              queryClient.invalidateQueries({ queryKey: ["users"] });
              setFeedback({ tone: "success", message });
            }}
            onLogout={() => handleLogout()}
          />
        )}

        {/* Le backend révoque TOUTES les sessions au changement de mot de
            passe, y compris celle-ci : elle tomberait sans explication au
            prochain renouvellement du jeton. On déconnecte donc tout de
            suite, en le disant. */}
        <PasswordPanel onChanged={() => handleLogout("password_changed")} />
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

/** Identifiants modifiables par l'utilisateur lui-même. */
function IdentityPanel({ user, onSaved, onLogout }) {
  const [form, setForm] = useState({
    username: user.username,
    full_name: user.full_name ?? "",
    phone_number: user.phone_number ?? "",
    email: user.email ?? "",
    notify_email: Boolean(user.notify_email),
  });
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const username = form.username.trim();
  const email = form.email.trim();
  const usernameChanged = username !== user.username;
  const usernameInvalid = username.length < 3 || !USERNAME_PATTERN.test(username);
  const emailInvalid = email.length > 0 && !EMAIL_PATTERN.test(email);
  const notifyWithoutEmail = form.notify_email && !email;

  const dirty =
    usernameChanged ||
    form.full_name.trim() !== (user.full_name ?? "") ||
    form.phone_number.trim() !== (user.phone_number ?? "") ||
    email !== (user.email ?? "") ||
    form.notify_email !== Boolean(user.notify_email);

  const canSubmit =
    dirty &&
    !pending &&
    form.full_name.trim() &&
    !usernameInvalid &&
    !emailInvalid &&
    !notifyWithoutEmail &&
    (!usernameChanged || currentPassword);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setPending(true);
    try {
      const payload = {
        full_name: form.full_name.trim(),
        phone_number: form.phone_number.trim() || null,
        email: email || null,
        notify_email: form.notify_email,
      };
      if (usernameChanged) {
        payload.username = username;
        payload.current_password = currentPassword;
      }
      const updated = await auth.updateMe(payload);
      setCurrentPassword("");
      onSaved(
        updated,
        usernameChanged
          ? `Identifiant modifié : connectez-vous désormais avec « ${updated.username} ».`
          : "Informations enregistrées.",
      );
    } catch (submitError) {
      setError(errorMessage(submitError));
    } finally {
      setPending(false);
    }
  };

  return (
    <Panel title="Identité et identifiants">
      <form onSubmit={submit} className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}

        <div className="grid grid-cols-2 gap-2.5">
          <Field
            label="Identifiant"
            required
            error={
              username.length > 0 && usernameInvalid
                ? "3 caractères minimum : lettres, chiffres, point, tiret."
                : null
            }
            hint="Sert à la connexion."
          >
            <input
              className="input"
              value={form.username}
              onChange={set("username")}
              autoComplete="username"
            />
          </Field>
          <Field label="Nom complet" required>
            <input className="input" value={form.full_name} onChange={set("full_name")} />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-2.5">
          <Field
            label="Courriel"
            error={
              emailInvalid
                ? "Adresse invalide."
                : notifyWithoutEmail
                  ? "Obligatoire pour recevoir les alertes."
                  : null
            }
          >
            <input
              className="input"
              type="email"
              value={form.email}
              onChange={set("email")}
              autoComplete="email"
            />
          </Field>
          <Field label="Téléphone">
            <input
              className="input"
              value={form.phone_number}
              onChange={set("phone_number")}
              autoComplete="tel"
            />
          </Field>
        </div>

        <label className="flex items-center gap-2 text-[12px] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={form.notify_email}
            onChange={(event) => setForm({ ...form, notify_email: event.target.checked })}
            style={{ accentColor: "var(--accent-ink)" }}
          />
          Recevoir les alertes graves par courriel
        </label>

        {usernameChanged && (
          <Field
            label="Mot de passe actuel"
            required
            hint="Exigé pour changer d'identifiant : c'est votre moyen de connexion qui change."
          >
            <input
              className="input"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
            />
          </Field>
        )}

        <button type="submit" className="btn btn-sm btn-primary" disabled={!canSubmit}>
          {pending ? "…" : "Enregistrer"}
        </button>
      </form>

      <div className="mt-3 pt-2.5 border-t" style={{ borderColor: "var(--border)" }}>
        <DefRow label="Rôle">
          <Badge color="var(--accent-ink)">{ROLE_LABEL[user.role] ?? user.role}</Badge>
          <span className="block text-[11px] mt-1" style={{ color: "var(--ink-3)" }}>
            {ROLE_DESCRIPTION[user.role]} Seul un Chef NOC peut modifier un rôle.
          </span>
        </DefRow>
        <DefRow label="Équipe">{user.team || "—"}</DefRow>
        <DefRow label="Matricule" mono>
          {user.employee_code || "—"}
        </DefRow>
        <DefRow label="Dernière connexion" mono>
          {user.last_login_at ? dateTime(user.last_login_at) : "—"}
        </DefRow>

        <div className="mt-3">
          <button type="button" className="btn btn-sm" onClick={onLogout}>
            <LogOut size={13} /> Se déconnecter
          </button>
        </div>
      </div>
    </Panel>
  );
}

function PasswordPanel({ onChanged }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  const changePassword = async (event) => {
    event.preventDefault();
    setError(null);
    if (newPassword !== confirmation) {
      setError("Les deux saisies ne correspondent pas.");
      return;
    }
    setPending(true);
    try {
      await auth.changePassword(currentPassword, newPassword);
      onChanged();
    } catch (changeError) {
      setError(errorMessage(changeError));
      setPending(false);
    }
  };

  return (
    <Panel title="Mot de passe">
      <form onSubmit={changePassword} className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
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
            confirmation && confirmation !== newPassword ? "Les deux saisies diffèrent." : null
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
        <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          Toutes vos sessions seront fermées, y compris celle-ci : reconnectez-vous avec le
          nouveau mot de passe.
        </p>
        <button
          type="submit"
          className="btn btn-sm btn-primary"
          disabled={
            pending || !currentPassword || newPassword.length < 8 || newPassword !== confirmation
          }
        >
          {pending ? "…" : "Modifier"}
        </button>
      </form>
    </Panel>
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

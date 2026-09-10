import { useMemo, useState } from "react";
import { KeyRound, Lock, Mail, Pencil, Send, ShieldOff, UserPlus } from "lucide-react";

import Panel from "../components/ui/Panel";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog, Modal } from "../components/ui/Overlay";
import { Field, Notice, SearchField, Toolbar } from "../components/ui/Controls";
import { DefRow } from "../components/ui/Stat";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { ROLE_DESCRIPTION, ROLE_LABEL, ROLES } from "../lib/permissions";
import { severityMeta } from "../lib/vocabulary";
import { dateTime, num } from "../lib/format";
import { errorMessage } from "../api/client";
import { useCurrentUser } from "../hooks/useSession";
import {
  useEmailStatus,
  useSendTestEmail,
  useSites,
  useUserActions,
  useUsers,
} from "../hooks/queries";

/**
 * Gestion des comptes — Chef NOC uniquement.
 *
 * Le rôle n'est pas un simple libellé : il détermine l'écran d'accueil,
 * les gestes autorisés et ce que le backend accepte. La liste déroulante
 * affiche donc la DESCRIPTION de chaque rôle, pas seulement son nom.
 *
 * Comportements imposés par le backend, expliqués dans l'interface :
 *
 * · un compte n'est jamais SUPPRIMÉ, seulement désactivé — supprimer une
 *   ligne de `noc_user` casserait la traçabilité « qui a résolu cet
 *   incident » (user_service.deactivate_user) ;
 * · changer le rôle d'un compte RÉVOQUE ses sessions en cours, parce que
 *   les jetons émis portent l'ancien rôle ;
 * · un Chef NOC ne change pas son propre rôle et ne désactive pas son
 *   propre compte : le dernier Chef NOC laisserait sinon la plateforme sans
 *   personne pour créer un compte.
 */

const ROLE_ORDER = [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN];

const ROLE_COLOR = {
  directeur: "var(--state-maintenance)",
  chef_noc: "var(--accent-ink)",
  technicien: "var(--sev-info)",
  agent_terrain: "var(--state-up)",
};

// Miroirs des motifs de backend/app/schemas/users.py : refuser la saisie ici
// évite un aller-retour voué au 422.
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;

export default function UsersPage() {
  const me = useCurrentUser();
  const users = useUsers();
  const actions = useUserActions();

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState(null);
  const [editing, setEditing] = useState(null); // objet utilisateur, ou "new"
  const [pinFor, setPinFor] = useState(null);
  const [passwordFor, setPasswordFor] = useState(null);
  const [toDeactivate, setToDeactivate] = useState(null);
  const [feedback, setFeedback] = useState(null);

  const rows = useMemo(() => {
    const list = users.data ?? [];
    return list.filter((user) => {
      if (roleFilter && user.role !== roleFilter) return false;
      if (!search) return true;
      const haystack =
        `${user.username} ${user.full_name ?? ""} ${user.team ?? ""} ${user.email ?? ""}`.toLowerCase();
      return haystack.includes(search.toLowerCase());
    });
  }, [users.data, search, roleFilter]);

  const countByRole = useMemo(() => {
    const counts = {};
    for (const user of users.data ?? []) {
      if (user.is_active) counts[user.role] = (counts[user.role] ?? 0) + 1;
    }
    return counts;
  }, [users.data]);

  const done = (message) => setFeedback({ tone: "success", message });

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Utilisateurs"
        subtitle="Comptes, rôles et destinataires des alertes"
        actions={
          <button type="button" className="btn btn-sm btn-primary" onClick={() => setEditing("new")}>
            <UserPlus size={13} /> Créer un compte
          </button>
        }
      />

      {feedback && (
        <Notice tone={feedback.tone} onClose={() => setFeedback(null)}>
          {feedback.message}
        </Notice>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {ROLE_ORDER.map((role) => (
          <button
            key={role}
            type="button"
            className="panel px-2.5 py-2 text-left"
            style={{
              borderColor: roleFilter === role ? ROLE_COLOR[role] : "var(--border)",
            }}
            onClick={() => setRoleFilter(roleFilter === role ? null : role)}
            title={ROLE_DESCRIPTION[role]}
          >
            <div
              className="text-[10.5px] uppercase tracking-[0.07em] flex items-center gap-1"
              style={{ color: "var(--ink-3)" }}
            >
              <span className="dot" style={{ background: ROLE_COLOR[role], width: 6, height: 6 }} />
              {ROLE_LABEL[role]}
            </div>
            <div className="num font-semibold" style={{ fontSize: 20 }}>
              {num(countByRole[role], "0")}
            </div>
          </button>
        ))}
      </div>

      <Panel title="Comptes" flush>
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              roleFilter && (
                <button type="button" className="btn btn-sm" onClick={() => setRoleFilter(null)}>
                  Tous les rôles
                </button>
              )
            }
          >
            <SearchField
              value={search}
              onChange={setSearch}
              placeholder="Nom, identifiant, équipe, courriel…"
              width={240}
            />
          </Toolbar>
        </div>

        <QueryBoundary
          query={users}
          empty={() => rows.length === 0}
          emptyMessage="Aucun compte ne correspond"
        >
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Nom</th>
                  <th style={{ width: 130 }}>Identifiant</th>
                  <th style={{ width: 130 }}>Rôle</th>
                  <th style={{ width: 110 }}>Équipe</th>
                  <th style={{ width: 200 }}>Courriel</th>
                  <th style={{ width: 120 }}>Téléphone</th>
                  <th style={{ width: 50 }}>PIN</th>
                  <th style={{ width: 130 }}>Dernière connexion</th>
                  <th style={{ width: 85 }}>État</th>
                  <th style={{ width: 120 }} />
                </tr>
              </thead>
              <tbody>
                {rows.map((user) => {
                  const isSelf = user.id === me?.id;
                  return (
                    <tr key={user.id} style={{ opacity: user.is_active ? 1 : 0.55 }}>
                      <td className="font-medium">
                        {user.full_name || "—"}
                        {isSelf && (
                          <span className="text-[10.5px] ml-1.5" style={{ color: "var(--ink-3)" }}>
                            (vous)
                          </span>
                        )}
                      </td>
                      <td className="mono-xs" style={{ color: "var(--ink-2)" }}>
                        {user.username}
                      </td>
                      <td>
                        <Badge color={ROLE_COLOR[user.role]} title={ROLE_DESCRIPTION[user.role]}>
                          {ROLE_LABEL[user.role] ?? user.role}
                        </Badge>
                      </td>
                      <td style={{ color: "var(--ink-3)" }}>{user.team || "—"}</td>
                      <td className="mono-xs" style={{ color: "var(--ink-3)" }}>
                        {user.email ? (
                          <span
                            className="inline-flex items-center gap-1"
                            title={
                              user.notify_email
                                ? "Reçoit les alertes graves par courriel"
                                : "Adresse renseignée, alertes non souscrites"
                            }
                          >
                            <Mail
                              size={11}
                              style={{
                                color: user.notify_email ? "var(--state-up)" : "var(--ink-3)",
                                flexShrink: 0,
                              }}
                            />
                            {user.email}
                          </span>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="mono-xs" style={{ color: "var(--ink-3)" }}>
                        {user.phone_number || "—"}
                      </td>
                      <td>
                        {user.has_pin ? (
                          <span style={{ color: "var(--state-up)" }} title="Connexion par PIN activée">
                            oui
                          </span>
                        ) : (
                          <span style={{ color: "var(--ink-3)" }}>non</span>
                        )}
                      </td>
                      <td className="num" style={{ color: "var(--ink-3)" }}>
                        {user.last_login_at ? dateTime(user.last_login_at) : "jamais"}
                      </td>
                      <td>
                        <Badge color={user.is_active ? "var(--state-up)" : "var(--ink-3)"}>
                          {user.is_active ? "Actif" : "Désactivé"}
                        </Badge>
                      </td>
                      <td>
                        <div className="flex items-center gap-0.5 justify-end">
                          <button
                            type="button"
                            className="btn btn-ghost btn-sm"
                            title="Modifier"
                            onClick={() => setEditing(user)}
                          >
                            <Pencil size={12} />
                          </button>
                          {!isSelf && user.is_active && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              title="Réinitialiser le mot de passe"
                              onClick={() => setPasswordFor(user)}
                            >
                              <Lock size={12} />
                            </button>
                          )}
                          {user.role === ROLES.AGENT_TERRAIN && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              title="Définir un code PIN"
                              onClick={() => setPinFor(user)}
                            >
                              <KeyRound size={12} />
                            </button>
                          )}
                          {user.is_active && !isSelf && (
                            <button
                              type="button"
                              className="btn btn-ghost btn-sm"
                              title="Désactiver ce compte"
                              onClick={() => setToDeactivate(user)}
                            >
                              <ShieldOff size={12} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </QueryBoundary>
      </Panel>

      <EmailAlertsPanel />

      {/* Aide-mémoire des rôles : évite d'aller lire la documentation
          pour savoir ce qu'on est en train d'accorder. */}
      <Panel title="Ce que chaque rôle peut faire">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
          {ROLE_ORDER.map((role) => (
            <div key={role}>
              <div className="flex items-center gap-1.5 mb-1">
                <span className="dot" style={{ background: ROLE_COLOR[role] }} />
                <span className="text-[12px] font-semibold">{ROLE_LABEL[role]}</span>
              </div>
              <p className="text-[11.5px] leading-snug" style={{ color: "var(--ink-3)" }}>
                {ROLE_DESCRIPTION[role]}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {editing && (
        <UserFormModal
          user={editing === "new" ? null : editing}
          isSelf={editing !== "new" && editing.id === me?.id}
          onClose={() => setEditing(null)}
          actions={actions}
          onDone={(message) => {
            done(message);
            setEditing(null);
          }}
        />
      )}

      {pinFor && (
        <PinModal
          user={pinFor}
          onClose={() => setPinFor(null)}
          actions={actions}
          onDone={(message) => {
            done(message);
            setPinFor(null);
          }}
        />
      )}

      {passwordFor && (
        <PasswordResetModal
          user={passwordFor}
          onClose={() => setPasswordFor(null)}
          actions={actions}
          onDone={(message) => {
            done(message);
            setPasswordFor(null);
          }}
        />
      )}

      <ConfirmDialog
        open={Boolean(toDeactivate)}
        onClose={() => setToDeactivate(null)}
        pending={actions.deactivate.isPending}
        title="Désactiver le compte"
        message={
          toDeactivate
            ? `${toDeactivate.full_name || toDeactivate.username} ne pourra plus se connecter, ses sessions en cours seront coupées et il ne recevra plus d'alertes. Le compte n'est pas supprimé : son historique d'actions reste consultable.`
            : ""
        }
        confirmLabel="Désactiver"
        onConfirm={async () => {
          try {
            await actions.deactivate.mutateAsync(toDeactivate.id);
            done("Compte désactivé.");
          } catch (error) {
            setFeedback({ tone: "error", message: errorMessage(error) });
          }
          setToDeactivate(null);
        }}
      />
    </div>
  );
}

const SECURITY_LABEL = {
  ssl: "TLS implicite (SMTPS)",
  starttls: "STARTTLS",
  none: "sans chiffrement",
};

/**
 * État de la chaîne courriel et envoi d'un test.
 *
 * Le test existe pour qu'on ne découvre pas un mot de passe SMTP erroné le
 * jour d'une vraie panne : il passe par exactement le même chemin qu'une
 * alerte, et rend le message du serveur SMTP tel quel en cas d'échec.
 */
function EmailAlertsPanel() {
  const status = useEmailStatus();
  const sendTest = useSendTestEmail();
  const [result, setResult] = useState(null);
  const data = status.data;

  let state = null;
  if (data) {
    if (!data.smtp_configured) state = { label: "SMTP non configuré", color: "var(--sev-critical)" };
    else if (!data.notifications_enabled) state = { label: "Envoi coupé", color: "var(--sev-medium)" };
    else if (data.recipients.length === 0) state = { label: "Aucun destinataire", color: "var(--sev-medium)" };
    else state = { label: "Opérationnel", color: "var(--state-up)" };
  }

  const sendTestEmail = async () => {
    setResult(null);
    try {
      const { sent_to: sentTo } = await sendTest.mutateAsync();
      setResult({ tone: "success", message: `Courriel de test envoyé à ${sentTo.join(", ")}.` });
    } catch (error) {
      setResult({ tone: "error", message: errorMessage(error) });
    }
  };

  return (
    <Panel
      title="Alertes par courriel"
      subtitle="Incidents graves envoyés aux comptes abonnés"
      actions={
        <button
          type="button"
          className="btn btn-sm"
          onClick={sendTestEmail}
          disabled={sendTest.isPending || !data?.smtp_configured || !data?.recipients.length}
        >
          <Send size={12} /> {sendTest.isPending ? "Envoi…" : "Envoyer un test"}
        </button>
      }
    >
      <QueryBoundary query={status}>
        {data && (
          <div className="space-y-2">
            {result && (
              <Notice tone={result.tone} onClose={() => setResult(null)}>
                {result.message}
              </Notice>
            )}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6">
              <div>
                <DefRow label="État">
                  <Badge color={state.color}>{state.label}</Badge>
                </DefRow>
                <DefRow label="Serveur" mono>
                  {data.smtp_host
                    ? `${data.smtp_host}:${data.smtp_port} · ${SECURITY_LABEL[data.security]}`
                    : "—"}
                </DefRow>
                <DefRow label="Expéditeur" mono>
                  {data.sender}
                </DefRow>
                <DefRow label="Gravités">
                  {data.severities.map((severity) => severityMeta(severity).label).join(", ")}
                </DefRow>
              </div>
              <div>
                <DefRow label="Destinataires" mono>
                  {data.recipients.length ? data.recipients.join(", ") : "Aucun"}
                </DefRow>
                {data.fixed_recipients.length > 0 && (
                  <DefRow label="Listes fixes" mono>
                    {data.fixed_recipients.join(", ")}
                  </DefRow>
                )}
              </div>
            </div>
            {!data.smtp_configured && (
              <Notice tone="warning">
                Aucun serveur SMTP : renseignez SMTP_HOST et les variables associées dans .env,
                puis redémarrez le backend.
              </Notice>
            )}
            {data.smtp_configured && !data.notifications_enabled && (
              <Notice tone="warning">
                Le serveur SMTP est configuré mais l'envoi automatique est coupé
                (NOTIFICATIONS_ENABLED=false). Le test fonctionne quand même : validez la
                configuration, puis activez l'envoi.
              </Notice>
            )}
            <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
              Pour ajouter un destinataire, modifiez son compte : adresse courriel et case
              « Recevoir les alertes ». Chacun peut aussi s'abonner depuis « Mon compte ».
            </p>
          </div>
        )}
      </QueryBoundary>
    </Panel>
  );
}

/** Création et modification d'un compte. */
function UserFormModal({ user, isSelf, onClose, actions, onDone }) {
  const isNew = !user;
  const { data: sites } = useSites();

  const [form, setForm] = useState({
    username: user?.username ?? "",
    full_name: user?.full_name ?? "",
    role: user?.role ?? ROLES.TECHNICIEN,
    password: "",
    pin: "",
    phone_number: user?.phone_number ?? "",
    email: user?.email ?? "",
    notify_email: user?.notify_email ?? false,
    team: user?.team ?? "",
    employee_code: user?.employee_code ?? "",
    site: user?.site ?? "",
  });
  const [error, setError] = useState(null);

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const username = form.username.trim();
  const email = form.email.trim();
  const usernameInvalid = isNew && username.length > 0 && !USERNAME_PATTERN.test(username);
  const passwordTooShort = isNew && form.password.length > 0 && form.password.length < 8;
  const emailInvalid = email.length > 0 && !EMAIL_PATTERN.test(email);
  const notifyWithoutEmail = form.notify_email && !email;

  const valid =
    (isNew
      ? username.length >= 3 && !usernameInvalid && form.full_name.trim() && form.password.length >= 8
      : form.full_name.trim()) &&
    !emailInvalid &&
    !notifyWithoutEmail;

  const submit = async () => {
    setError(null);
    const common = {
      full_name: form.full_name.trim(),
      phone_number: form.phone_number.trim() || null,
      email: email || null,
      notify_email: form.notify_email,
      team: form.team.trim() || null,
      employee_code: form.employee_code.trim() || null,
      site: form.site.trim() || null,
    };
    try {
      if (isNew) {
        await actions.create.mutateAsync({
          ...common,
          username,
          role: form.role,
          password: form.password,
          pin: form.pin || null,
        });
        onDone(`Compte « ${username} » créé. Il peut se connecter immédiatement.`);
      } else {
        const roleChanged = form.role !== user.role;
        await actions.update.mutateAsync({
          userId: user.id,
          // Le rôle n'est envoyé que s'il change : le backend coupe les
          // sessions du compte à chaque changement de rôle.
          payload: roleChanged ? { ...common, role: form.role } : common,
        });
        onDone(
          roleChanged
            ? "Compte mis à jour. Le changement de rôle a coupé ses sessions en cours."
            : "Compte mis à jour.",
        );
      }
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  const pending = actions.create.isPending || actions.update.isPending;

  return (
    <Modal
      open
      onClose={onClose}
      title={isNew ? "Créer un compte" : `Modifier ${user.username}`}
      subtitle={isNew ? "L'utilisateur pourra se connecter dès la création." : undefined}
      width={560}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={!valid || pending}
            onClick={submit}
          >
            {pending ? "…" : isNew ? "Créer le compte" : "Enregistrer"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}

        <div className="grid grid-cols-2 gap-2.5">
          <Field
            label="Identifiant"
            required
            error={usernameInvalid ? "Lettres, chiffres, point, tiret ou souligné." : null}
            hint={
              isNew
                ? "3 caractères minimum. L'utilisateur pourra le changer lui-même."
                : "Modifiable par l'utilisateur, depuis « Mon compte »."
            }
          >
            <input
              className="input"
              value={form.username}
              onChange={set("username")}
              disabled={!isNew}
              autoFocus={isNew}
              placeholder="k.ouedraogo"
            />
          </Field>
          <Field label="Nom complet" required>
            <input
              className="input"
              value={form.full_name}
              onChange={set("full_name")}
              placeholder="Karim Ouédraogo"
            />
          </Field>
        </div>

        <Field
          label="Rôle"
          required
          hint={
            isSelf
              ? "Vous ne pouvez pas modifier votre propre rôle : demandez-le à un autre Chef NOC."
              : ROLE_DESCRIPTION[form.role]
          }
        >
          <select className="select" value={form.role} onChange={set("role")} disabled={isSelf}>
            {ROLE_ORDER.map((role) => (
              <option key={role} value={role}>
                {ROLE_LABEL[role]}
              </option>
            ))}
          </select>
        </Field>

        {isNew && (
          <div className="grid grid-cols-2 gap-2.5">
            <Field
              label="Mot de passe provisoire"
              required
              error={passwordTooShort ? "8 caractères minimum." : null}
              hint={passwordTooShort ? undefined : "À transmettre ; modifiable depuis « Mon compte »."}
            >
              <input
                className="input"
                type="text"
                value={form.password}
                onChange={set("password")}
                autoComplete="off"
              />
            </Field>
            <Field
              label="Code PIN"
              hint={
                form.role === ROLES.AGENT_TERRAIN
                  ? "4 à 6 chiffres — connexion rapide sur console partagée."
                  : "Sans effet : seuls les agents terrain se connectent par PIN."
              }
            >
              <input
                className="input"
                value={form.pin}
                onChange={set("pin")}
                inputMode="numeric"
                pattern="\d*"
                maxLength={6}
                placeholder="1234"
                disabled={form.role !== ROLES.AGENT_TERRAIN}
              />
            </Field>
          </div>
        )}

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
              placeholder="k.ouedraogo@anptic.bf"
            />
          </Field>
          <Field label="Téléphone">
            <input
              className="input"
              value={form.phone_number}
              onChange={set("phone_number")}
              placeholder="+226…"
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

        <div className="grid grid-cols-3 gap-2.5">
          <Field label="Équipe">
            <input className="input" value={form.team} onChange={set("team")} placeholder="Quart A" />
          </Field>
          <Field label="Matricule">
            <input
              className="input"
              value={form.employee_code}
              onChange={set("employee_code")}
            />
          </Field>
          <Field label="Site" hint="Tel que les outils le nomment.">
            <input
              className="input"
              value={form.site}
              onChange={set("site")}
              list="user-form-sites"
            />
            <datalist id="user-form-sites">
              {(sites ?? []).map((entry) => (
                <option key={entry.site} value={entry.site} />
              ))}
            </datalist>
          </Field>
        </div>

        {!isNew && form.role !== user.role && (
          <Notice tone="warning">
            Changer le rôle coupera les sessions en cours de cet utilisateur : ses jetons
            portent l'ancien rôle et seraient refusés.
          </Notice>
        )}
      </div>
    </Modal>
  );
}

function PasswordResetModal({ user, onClose, actions, onDone }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  const submit = async () => {
    setError(null);
    try {
      await actions.resetPassword.mutateAsync({ userId: user.id, password });
      onDone(
        `Mot de passe de ${user.full_name || user.username} réinitialisé et sessions coupées. ` +
          "Transmettez-lui le mot de passe provisoire ; il le changera depuis « Mon compte ».",
      );
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Réinitialiser le mot de passe"
      subtitle={`${user.full_name || user.username} — mot de passe oublié`}
      width={400}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={password.length < 8 || actions.resetPassword.isPending}
            onClick={submit}
          >
            {actions.resetPassword.isPending ? "…" : "Réinitialiser"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Mot de passe provisoire" required hint="8 caractères minimum.">
          <input
            className="input"
            type="text"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="off"
            autoFocus
          />
        </Field>
        <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          Toutes ses sessions en cours sont coupées : si l'oubli cache une compromission,
          l'ancien mot de passe n'ouvre plus rien.
        </p>
      </div>
    </Modal>
  );
}

function PinModal({ user, onClose, actions, onDone }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState(null);

  const submit = async () => {
    setError(null);
    try {
      await actions.resetPin.mutateAsync({ userId: user.id, pin });
      onDone(`Code PIN mis à jour pour ${user.full_name || user.username}.`);
    } catch (submitError) {
      setError(errorMessage(submitError));
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Code PIN"
      subtitle={`${user.full_name || user.username} — connexion rapide sur console partagée`}
      width={380}
      footer={
        <>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Annuler
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={pin.length < 4 || actions.resetPin.isPending}
            onClick={submit}
          >
            {actions.resetPin.isPending ? "…" : "Définir"}
          </button>
        </>
      }
    >
      <div className="space-y-2.5">
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Nouveau code" required hint="4 à 6 chiffres.">
          <input
            className="input num"
            value={pin}
            onChange={(event) => setPin(event.target.value.replace(/\D/g, "").slice(0, 6))}
            inputMode="numeric"
            autoFocus
          />
        </Field>
        <p className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
          Le PIN est un facteur faible, réservé aux agents terrain. Deux comptes ne
          peuvent pas partager le même code.
        </p>
      </div>
    </Modal>
  );
}

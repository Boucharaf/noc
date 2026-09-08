import { useMemo, useState } from "react";
import { KeyRound, Pencil, ShieldOff, UserPlus } from "lucide-react";

import Panel from "../components/ui/Panel";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog, Modal } from "../components/ui/Overlay";
import { Field, Notice, SearchField, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { QueryBoundary } from "../components/ui/States";
import { ROLE_DESCRIPTION, ROLE_LABEL, ROLES } from "../lib/permissions";
import { dateTime, num } from "../lib/format";
import { errorMessage } from "../api/client";
import { useCurrentUser } from "../hooks/useSession";
import { useReference, useUserActions, useUsers } from "../hooks/queries";

/**
 * Gestion des comptes.
 *
 * Le rôle n'est pas un simple libellé : il détermine l'écran d'accueil,
 * les gestes autorisés et ce que le backend accepte. La liste déroulante
 * affiche donc la DESCRIPTION de chaque rôle, pas seulement son nom —
 * « Chef NOC » ne dit pas qu'il est le seul à pouvoir affecter un
 * incident.
 *
 * Deux comportements imposés par le backend, expliqués dans l'interface :
 *
 * · un compte n'est jamais SUPPRIMÉ, seulement désactivé — supprimer une
 *   ligne de `dim_user` emporterait ou casserait la traçabilité « qui a
 *   résolu cet incident » (user_service.deactivate_user) ;
 * · changer le rôle d'un compte RÉVOQUE ses sessions en cours, parce que
 *   les jetons émis portent l'ancien rôle.
 */

const ROLE_ORDER = [ROLES.DIRECTEUR, ROLES.CHEF_NOC, ROLES.TECHNICIEN, ROLES.AGENT_TERRAIN];

const ROLE_COLOR = {
  directeur: "var(--state-maintenance)",
  chef_noc: "var(--accent-ink)",
  technicien: "var(--sev-info)",
  agent_terrain: "var(--state-up)",
};

export default function UsersPage() {
  const me = useCurrentUser();
  const users = useUsers();
  const actions = useUserActions();

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState(null);
  const [editing, setEditing] = useState(null); // objet utilisateur, ou "new"
  const [pinFor, setPinFor] = useState(null);
  const [toDeactivate, setToDeactivate] = useState(null);
  const [feedback, setFeedback] = useState(null);

  const rows = useMemo(() => {
    const list = users.data ?? [];
    return list.filter((user) => {
      if (roleFilter && user.role !== roleFilter) return false;
      if (!search) return true;
      const haystack = `${user.username} ${user.full_name ?? ""} ${user.team ?? ""}`.toLowerCase();
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

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Utilisateurs"
        subtitle="Comptes, rôles et périmètres d'accès"
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
              placeholder="Nom, identifiant, équipe…"
              width={220}
            />
          </Toolbar>
        </div>

        <QueryBoundary
          query={users}
          empty={() => rows.length === 0}
          emptyMessage="Aucun compte ne correspond"
        >
          <table className="tbl">
            <thead>
              <tr>
                <th>Nom</th>
                <th style={{ width: 140 }}>Identifiant</th>
                <th style={{ width: 140 }}>Rôle</th>
                <th style={{ width: 120 }}>Équipe</th>
                <th style={{ width: 130 }}>Téléphone</th>
                <th style={{ width: 60 }}>PIN</th>
                <th style={{ width: 140 }}>Dernière connexion</th>
                <th style={{ width: 90 }}>État</th>
                <th style={{ width: 100 }} />
              </tr>
            </thead>
            <tbody>
              {rows.map((user) => (
                <tr key={user.id} style={{ opacity: user.is_active ? 1 : 0.55 }}>
                  <td className="font-medium">
                    {user.full_name || "—"}
                    {user.id === me?.id && (
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
                      {user.is_active && user.id !== me?.id && (
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
              ))}
            </tbody>
          </table>
        </QueryBoundary>
      </Panel>

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
          onClose={() => setEditing(null)}
          actions={actions}
          onDone={(message) => {
            setFeedback({ tone: "success", message });
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
            setFeedback({ tone: "success", message });
            setPinFor(null);
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
            ? `${toDeactivate.full_name || toDeactivate.username} ne pourra plus se connecter et ses sessions en cours seront coupées. Le compte n'est pas supprimé : son historique d'actions reste consultable.`
            : ""
        }
        confirmLabel="Désactiver"
        onConfirm={async () => {
          await actions.deactivate.mutateAsync(toDeactivate.id);
          setFeedback({ tone: "success", message: "Compte désactivé." });
          setToDeactivate(null);
        }}
      />
    </div>
  );
}

/** Création et modification d'un compte. */
function UserFormModal({ user, onClose, actions, onDone }) {
  const isNew = !user;
  const { data: reference } = useReference();

  const [form, setForm] = useState({
    username: user?.username ?? "",
    full_name: user?.full_name ?? "",
    role: user?.role ?? ROLES.TECHNICIEN,
    password: "",
    pin: "",
    phone_number: user?.phone_number ?? "",
    team: user?.team ?? "",
    employee_code: user?.employee_code ?? "",
    region_id: user?.region_id ?? "",
    locality_id: user?.locality_id ?? "",
    ministry_id: user?.ministry_id ?? "",
  });
  const [error, setError] = useState(null);

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });

  const numberOrNull = (value) => (value === "" || value === null ? null : Number(value));

  const passwordTooShort = isNew && form.password.length > 0 && form.password.length < 8;
  const valid = isNew
    ? form.username.trim().length >= 3 && form.full_name.trim() && form.password.length >= 8
    : form.full_name.trim();

  const submit = async () => {
    setError(null);
    try {
      if (isNew) {
        await actions.create.mutateAsync({
          username: form.username.trim(),
          full_name: form.full_name.trim(),
          role: form.role,
          password: form.password,
          pin: form.pin || null,
          phone_number: form.phone_number || null,
          team: form.team || null,
          employee_code: form.employee_code || null,
          region_id: numberOrNull(form.region_id),
          locality_id: numberOrNull(form.locality_id),
          ministry_id: numberOrNull(form.ministry_id),
        });
        onDone(`Compte « ${form.username.trim()} » créé. Il peut se connecter immédiatement.`);
      } else {
        await actions.update.mutateAsync({
          userId: user.id,
          payload: {
            full_name: form.full_name.trim(),
            role: form.role,
            phone_number: form.phone_number || null,
            team: form.team || null,
            employee_code: form.employee_code || null,
            region_id: numberOrNull(form.region_id),
            locality_id: numberOrNull(form.locality_id),
            ministry_id: numberOrNull(form.ministry_id),
          },
        });
        onDone(
          form.role !== user.role
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
      width={540}
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
            hint={isNew ? "3 caractères minimum, non modifiable ensuite." : undefined}
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

        <Field label="Rôle" required hint={ROLE_DESCRIPTION[form.role]}>
          <select className="select" value={form.role} onChange={set("role")}>
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
              label="Mot de passe"
              required
              error={passwordTooShort ? "8 caractères minimum." : null}
              hint={passwordTooShort ? undefined : "8 caractères minimum."}
            >
              <input
                className="input"
                type="text"
                value={form.password}
                onChange={set("password")}
                placeholder="À transmettre à l'utilisateur"
              />
            </Field>
            <Field
              label="Code PIN"
              hint={
                form.role === ROLES.AGENT_TERRAIN
                  ? "4 à 6 chiffres — connexion rapide sur console partagée."
                  : "Sans effet : seuls les agents terrain peuvent se connecter par PIN."
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

        <div className="grid grid-cols-3 gap-2.5">
          <Field label="Téléphone" hint="Pour les alertes SMS.">
            <input
              className="input"
              value={form.phone_number}
              onChange={set("phone_number")}
              placeholder="+226…"
            />
          </Field>
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
        </div>

        <div
          className="pt-2 border-t"
          style={{ borderColor: "var(--border)" }}
        >
          <p className="text-[10.5px] mb-2" style={{ color: "var(--ink-3)" }}>
            Périmètre géographique — facultatif, sert à contextualiser les écrans et les
            alertes envoyées à cet utilisateur.
          </p>
          <div className="grid grid-cols-3 gap-2.5">
            <Field label="Région">
              <select className="select" value={form.region_id} onChange={set("region_id")}>
                <option value="">Aucune</option>
                {(reference?.regions ?? []).map((region) => (
                  <option key={region.id} value={region.id}>
                    {region.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Site">
              <select className="select" value={form.locality_id} onChange={set("locality_id")}>
                <option value="">Aucun</option>
                {(reference?.localities ?? []).map((locality) => (
                  <option key={locality.id} value={locality.id}>
                    {locality.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Ministère">
              <select className="select" value={form.ministry_id} onChange={set("ministry_id")}>
                <option value="">Aucun</option>
                {(reference?.ministries ?? []).map((ministry) => (
                  <option key={ministry.id} value={ministry.id}>
                    {ministry.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
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

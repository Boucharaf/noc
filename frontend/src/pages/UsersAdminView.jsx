import React, { useState } from "react";
import { Users, PlusCircle, KeyRound, UserX, X } from "lucide-react";
import Card from "../components/Card";
import { ROLE_LABEL } from "../components/layout/Header";
import { useUsers, useCreateUser, useDeactivateUser, useResetUserPin } from "../hooks/useUsers";
import { ROLES } from "../api/permissions";
import { STATUS } from "../theme/colors";

const EMPTY_FORM = {
  username: "", fullName: "", role: ROLES.TECHNICIEN, password: "", pin: "",
  phoneNumber: "", employeeCode: "", team: "",
};

const CreateUserDialog = ({ onClose }) => {
  const [form, setForm] = useState(EMPTY_FORM);
  const create = useCreateUser();

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = (e) => {
    e.preventDefault();
    create.mutate(form, { onSuccess: onClose });
  };

  const field = (label, key, props = {}) => (
    <div>
      <label className="mb-1 block text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>{label}</label>
      <input
        value={form[key]}
        onChange={set(key)}
        className="w-full rounded-md border p-2 text-sm outline-none"
        style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
        {...props}
      />
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form onSubmit={submit} className="w-full max-w-lg rounded-xl border p-4" style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold">Nouvel utilisateur</h3>
          <button type="button" onClick={onClose} className="rounded-md p-1 hover:bg-[var(--color-surface-2)]"><X className="h-4 w-4" /></button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {field("Nom complet", "fullName", { required: true })}
          {field("Identifiant", "username", { required: true, minLength: 3 })}
          <div>
            <label className="mb-1 block text-xs font-medium" style={{ color: "var(--color-text-secondary)" }}>Rôle</label>
            <select
              value={form.role}
              onChange={set("role")}
              className="w-full rounded-md border p-2 text-sm outline-none"
              style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
            >
              {Object.values(ROLES).map((r) => (
                <option key={r} value={r}>{ROLE_LABEL[r]}</option>
              ))}
            </select>
          </div>
          {field("Mot de passe (min. 8 car.)", "password", { type: "password", required: true, minLength: 8 })}
          {field("PIN (optionnel, 4-6 chiffres)", "pin", { pattern: "[0-9]*" })}
          {field("Téléphone", "phoneNumber")}
          {field("Matricule", "employeeCode")}
          {field("Équipe", "team")}
        </div>
        {create.isError && (
          <p className="mt-3 text-xs" style={{ color: STATUS.critical }}>
            {create.error?.response?.data?.detail ?? "Échec de la création."}
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>Annuler</button>
          <button type="submit" disabled={create.isPending} className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "var(--color-accent)" }}>
            {create.isPending ? "Création…" : "Créer"}
          </button>
        </div>
      </form>
    </div>
  );
};

const ResetPinDialog = ({ user, onClose }) => {
  const [pin, setPin] = useState("");
  const resetPin = useResetUserPin();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <form
        onSubmit={(e) => { e.preventDefault(); resetPin.mutate({ userId: user.id, newPin: pin }, { onSuccess: onClose }); }}
        className="w-full max-w-sm rounded-xl border p-4"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border-strong)", boxShadow: "var(--shadow-elevate)" }}
      >
        <h3 className="mb-3 text-sm font-semibold">Réinitialiser le PIN de {user.full_name}</h3>
        <input
          value={pin}
          onChange={(e) => setPin(e.target.value)}
          pattern="[0-9]*"
          placeholder="Nouveau PIN (4-6 chiffres)"
          className="mb-3 w-full rounded-md border p-2 text-sm outline-none"
          style={{ borderColor: "var(--color-border)", background: "var(--color-page)", color: "var(--color-text-primary)" }}
        />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-md px-3 py-1.5 text-sm font-medium" style={{ color: "var(--color-text-secondary)" }}>Annuler</button>
          <button type="submit" disabled={!pin || resetPin.isPending} className="rounded-md px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50" style={{ background: "var(--color-accent)" }}>
            {resetPin.isPending ? "…" : "Réinitialiser"}
          </button>
        </div>
      </form>
    </div>
  );
};

const UsersAdminView = () => {
  const { data: users = [], isLoading } = useUsers();
  const deactivate = useDeactivateUser();
  const [showCreate, setShowCreate] = useState(false);
  const [pinTarget, setPinTarget] = useState(null);

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold">Utilisateurs</h1>
          <p className="text-xs" style={{ color: "var(--color-text-secondary)" }}>Comptes ayant accès au tableau de bord NOC</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold text-white"
          style={{ background: "var(--color-accent)" }}
        >
          <PlusCircle className="h-3.5 w-3.5" /> Nouvel utilisateur
        </button>
      </div>

      <Card icon={Users} title={`${users.length} utilisateur(s)`} bodyClassName="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs font-medium" style={{ borderColor: "var(--color-border)", color: "var(--color-text-secondary)" }}>
                <th className="px-3 py-2">Nom</th>
                <th className="px-3 py-2">Identifiant</th>
                <th className="px-3 py-2">Rôle</th>
                <th className="px-3 py-2">Équipe</th>
                <th className="px-3 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y" style={{ borderColor: "var(--color-border)" }}>
              {isLoading && (
                <tr><td colSpan={5} className="px-3 py-6 text-center" style={{ color: "var(--color-text-muted)" }}>Chargement…</td></tr>
              )}
              {!isLoading && users.length === 0 && (
                <tr><td colSpan={5} className="px-3 py-6 text-center" style={{ color: "var(--color-text-muted)" }}>Aucun utilisateur.</td></tr>
              )}
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-3 py-2 font-medium">{u.full_name}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: "var(--color-text-secondary)" }}>{u.username}</td>
                  <td className="px-3 py-2">{ROLE_LABEL[u.role] ?? u.role}</td>
                  <td className="px-3 py-2" style={{ color: "var(--color-text-secondary)" }}>{u.team ?? "—"}</td>
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => setPinTarget(u)} title="Réinitialiser le PIN" className="rounded-md p-1.5 hover:bg-[var(--color-surface-2)]">
                        <KeyRound className="h-4 w-4" style={{ color: "var(--color-text-muted)" }} />
                      </button>
                      <button
                        onClick={() => { if (confirm(`Désactiver le compte de ${u.full_name} ?`)) deactivate.mutate(u.id); }}
                        title="Désactiver"
                        className="rounded-md p-1.5 hover:bg-[var(--color-surface-2)]"
                      >
                        <UserX className="h-4 w-4" style={{ color: STATUS.critical }} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {showCreate && <CreateUserDialog onClose={() => setShowCreate(false)} />}
      {pinTarget && <ResetPinDialog user={pinTarget} onClose={() => setPinTarget(null)} />}
    </div>
  );
};

export default UsersAdminView;

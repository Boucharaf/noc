import { useState } from "react";

/**
 * Page de création d'utilisateur — NOC Dashboard
 *
 * Correspond au schéma dim_user et à app/services/auth_service.py :
 *  - password_hash : bcrypt (obligatoire, vérifié par authenticate_with_password)
 *  - pin_hash      : SHA-256 non salé (optionnel, "convenience credential" —
 *                    jamais seul sur un compte sensible, voir docstring hash_pin)
 *
 * Le hashing se fait côté backend : ce composant envoie username/password/pin
 * en clair sur HTTPS vers POST /api/users, qui doit appeler hash_password()
 * et hash_pin() avant l'insertion. Ne jamais hasher côté client.
 *
 * Brancher l'appel réseau réel dans handleSubmit (ex: import { createUser }
 * from "../api/users"; en suivant le pattern de tes autres fichiers api/*.js).
 */

const ROLES = [
  {
    value: "directeur",
    label: "Directeur",
    description: "Vue globale, KPIs stratégiques, gestion des comptes",
    accent: "border-violet-500 bg-violet-500/10 text-violet-300",
    dot: "bg-violet-500",
  },
  {
    value: "chef_noc",
    label: "Chef NOC",
    description: "Supervision multi-site, escalade, rapports SLA",
    accent: "border-blue-500 bg-blue-500/10 text-blue-300",
    dot: "bg-blue-500",
  },
  {
    value: "technicien",
    label: "Technicien / Ingénieur",
    description: "Diagnostic, interventions, données techniques détaillées",
    accent: "border-emerald-500 bg-emerald-500/10 text-emerald-300",
    dot: "bg-emerald-500",
  },
  {
    value: "agent_terrain",
    label: "Agent terrain",
    description: "Interventions sur site, accès rapide par PIN en console partagée",
    accent: "border-amber-500 bg-amber-500/10 text-amber-300",
    dot: "bg-amber-500",
  },
];

const initialForm = {
  username: "",
  full_name: "",
  role: "",
  password: "",
  confirm_password: "",
  pin: "",
  confirm_pin: "",
  is_active: true,
};

function validate(form) {
  const errors = {};

  if (!form.username.trim()) {
    errors.username = "Identifiant requis.";
  } else if (!/^[a-z0-9._-]{3,32}$/i.test(form.username.trim())) {
    errors.username = "3 à 32 caractères : lettres, chiffres, point, tiret ou underscore.";
  }

  if (!form.full_name.trim()) {
    errors.full_name = "Nom complet requis.";
  }

  if (!form.role) {
    errors.role = "Sélectionnez un rôle.";
  }

  if (!form.password) {
    errors.password = "Mot de passe requis.";
  } else if (form.password.length < 10) {
    errors.password = "10 caractères minimum.";
  }

  if (form.password && form.confirm_password !== form.password) {
    errors.confirm_password = "Les mots de passe ne correspondent pas.";
  }

  // PIN optionnel — mais s'il est saisi, il doit être cohérent
  if (form.pin || form.confirm_pin) {
    if (!/^\d{4,6}$/.test(form.pin)) {
      errors.pin = "4 à 6 chiffres.";
    } else if (form.pin !== form.confirm_pin) {
      errors.confirm_pin = "Les codes PIN ne correspondent pas.";
    }
  }

  return errors;
}

export default function CreateUserPage({ onCreated } = {}) {
  const [form, setForm] = useState(initialForm);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState(null);
  const [success, setSuccess] = useState(false);

  const update = (field) => (e) => {
    const value = field === "is_active" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [field]: value }));
    if (errors[field]) setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const selectRole = (value) => {
    setForm((f) => ({ ...f, role: value }));
    if (errors.role) setErrors((prev) => ({ ...prev, role: undefined }));
  };

  async function handleSubmit(e) {
    e.preventDefault();
    setServerError(null);
    setSuccess(false);

    const validationErrors = validate(form);
    setErrors(validationErrors);
    if (Object.keys(validationErrors).length > 0) return;

    setSubmitting(true);
    try {
      // --- Brancher ici l'appel réel, ex :
      // const created = await createUser({
      //   username: form.username.trim(),
      //   full_name: form.full_name.trim(),
      //   role: form.role,
      //   password: form.password,
      //   pin: form.pin || null,
      //   is_active: form.is_active,
      // });
      await new Promise((resolve) => setTimeout(resolve, 600)); // placeholder réseau

      setSuccess(true);
      setForm(initialForm);
      onCreated?.(form.username.trim());
    } catch (err) {
      setServerError(
        err?.response?.status === 409
          ? "Cet identifiant existe déjà."
          : "Échec de la création. Vérifiez la connexion au backend."
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
      <div className="w-full max-w-3xl grid md:grid-cols-[1fr_1.4fr] gap-0 rounded-xl border border-slate-800 bg-slate-900/60 overflow-hidden">
        {/* Panneau contextuel */}
        <div className="p-8 border-b md:border-b-0 md:border-r border-slate-800 bg-slate-900/80">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400 mb-1">
            NOC Dashboard
          </h2>
          <h1 className="text-xl font-semibold text-slate-50 mb-6">
            Nouvel utilisateur
          </h1>
          <p className="text-sm text-slate-400 leading-relaxed mb-6">
            Le mot de passe est requis pour tous les rôles. Le code PIN est
            optionnel — il permet une connexion rapide sur les consoles NOC
            partagées, mais n'est jamais suffisant seul pour un compte
            sensible.
          </p>

          <div className="space-y-2">
            {ROLES.map((r) => (
              <div
                key={r.value}
                className={`flex items-start gap-2 text-xs rounded-md border px-3 py-2 ${
                  form.role === r.value ? r.accent : "border-slate-800 text-slate-500"
                }`}
              >
                <span className={`mt-1 h-1.5 w-1.5 rounded-full flex-shrink-0 ${r.dot}`} />
                <div>
                  <div className="font-medium">{r.label}</div>
                  <div className="opacity-80">{r.description}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Formulaire */}
        <form onSubmit={handleSubmit} className="p-8 space-y-5">
          {success && (
            <div className="rounded-md border border-emerald-700 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
              Utilisateur créé.
            </div>
          )}
          {serverError && (
            <div className="rounded-md border border-red-700 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {serverError}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field label="Identifiant" error={errors.username}>
              <input
                type="text"
                autoComplete="off"
                value={form.username}
                onChange={update("username")}
                placeholder="j.compaore"
                className={inputClass(errors.username)}
              />
            </Field>

            <Field label="Nom complet" error={errors.full_name}>
              <input
                type="text"
                value={form.full_name}
                onChange={update("full_name")}
                placeholder="Jean Compaoré"
                className={inputClass(errors.full_name)}
              />
            </Field>
          </div>

          <Field label="Rôle" error={errors.role}>
            <div className="grid grid-cols-2 gap-2">
              {ROLES.map((r) => (
                <button
                  type="button"
                  key={r.value}
                  onClick={() => selectRole(r.value)}
                  className={`text-left text-xs rounded-md border px-3 py-2 transition ${
                    form.role === r.value
                      ? r.accent
                      : "border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Mot de passe" error={errors.password}>
              <input
                type="password"
                autoComplete="new-password"
                value={form.password}
                onChange={update("password")}
                placeholder="10 caractères minimum"
                className={inputClass(errors.password)}
              />
            </Field>

            <Field label="Confirmation" error={errors.confirm_password}>
              <input
                type="password"
                autoComplete="new-password"
                value={form.confirm_password}
                onChange={update("confirm_password")}
                className={inputClass(errors.confirm_password)}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Code PIN (optionnel)" error={errors.pin}>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={form.pin}
                onChange={update("pin")}
                placeholder="4 à 6 chiffres"
                className={inputClass(errors.pin)}
              />
            </Field>

            <Field label="Confirmer le PIN" error={errors.confirm_pin}>
              <input
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={form.confirm_pin}
                onChange={update("confirm_pin")}
                className={inputClass(errors.confirm_pin)}
              />
            </Field>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={update("is_active")}
              className="h-4 w-4 rounded border-slate-600 bg-slate-800"
            />
            Compte actif dès la création
          </label>

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:cursor-not-allowed text-white text-sm font-medium py-2.5 transition"
          >
            {submitting ? "Création en cours…" : "Créer l'utilisateur"}
          </button>
        </form>
      </div>
    </div>
  );
}

function Field({ label, error, children }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-400 mb-1">{label}</label>
      {children}
      {error && <p className="mt-1 text-xs text-red-400">{error}</p>}
    </div>
  );
}

function inputClass(error) {
  return `w-full rounded-md bg-slate-800 border px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:ring-2 focus:ring-blue-500 ${
    error ? "border-red-500" : "border-slate-700"
  }`;
}

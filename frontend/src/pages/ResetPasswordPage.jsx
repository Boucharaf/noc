import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { Notice } from "../components/ui/Controls";
import { auth } from "../api/noc";
import { errorMessage } from "../api/client";

/**
 * Choix d'un nouveau mot de passe, depuis le lien reçu par courriel (INC-45).
 *
 * Page PUBLIQUE : on y arrive précisément parce qu'on ne peut plus se
 * connecter. Le jeton est dans l'adresse (`#jeton=`), à usage unique et de
 * courte durée ; le backend coupe toutes les sessions du compte une fois le
 * mot de passe changé.
 */
const MIN_LENGTH = 12;

export default function ResetPasswordPage() {
  const { hash, search } = useLocation();
  // `?jeton=` : liens envoyés avant le passage au fragment.
  const token =
    new URLSearchParams(hash.slice(1)).get("jeton") ?? new URLSearchParams(search).get("jeton") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const tooShort = password.length > 0 && password.length < MIN_LENGTH;
  const mismatch = confirm.length > 0 && confirm !== password;
  const ready = token && password.length >= MIN_LENGTH && password === confirm;

  const submit = async (event) => {
    event.preventDefault();
    if (!ready) return;
    setPending(true);
    setError(null);
    try {
      await auth.confirmPasswordReset(token, password);
      setDone(true);
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="light min-h-full flex items-center justify-center p-4" style={{ background: "#f4f7fb" }}>
      <div className="panel w-full" style={{ maxWidth: 400, padding: 24 }}>
        <img src="/images.png" alt="ANPTIC" style={{ height: 44, margin: "0 auto 12px", display: "block" }} />
        <h1 className="text-[16px] font-semibold mb-1" style={{ color: "var(--ink)" }}>
          Nouveau mot de passe
        </h1>

        {!token ? (
          <>
            <Notice tone="error">Lien incomplet. Ouvrez le lien reçu par courriel.</Notice>
            <Link to="/mot-de-passe-oublie" className="btn btn-primary w-full mt-3">
              Demander un nouveau lien
            </Link>
          </>
        ) : done ? (
          <>
            <Notice tone="success">
              Mot de passe changé. Par sécurité, toutes vos sessions ouvertes ont été fermées.
            </Notice>
            <Link to="/connexion" className="btn btn-primary w-full mt-3">
              Se connecter
            </Link>
          </>
        ) : (
          <form onSubmit={submit} className="flex flex-col gap-3 mt-2">
            {error && <Notice tone="error">{error}</Notice>}
            <label className="block">
              <span className="field-label">Nouveau mot de passe</span>
              <input
                className="input w-full"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                aria-invalid={tooShort}
              />
              <span className="block text-[12px] mt-1" style={{ color: tooShort ? "var(--sev-critical)" : "var(--ink-3)" }}>
                {MIN_LENGTH} caractères au moins.
              </span>
            </label>
            <label className="block">
              <span className="field-label">Confirmer le mot de passe</span>
              <input
                className="input w-full"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(event) => setConfirm(event.target.value)}
                aria-invalid={mismatch}
              />
              {mismatch && (
                <span className="block text-[12px] mt-1" style={{ color: "var(--sev-critical)" }}>
                  Les deux saisies diffèrent.
                </span>
              )}
            </label>
            <button type="submit" className="btn btn-primary w-full" disabled={!ready || pending}>
              {pending ? "Enregistrement…" : "Enregistrer le mot de passe"}
            </button>
            <Link to="/mot-de-passe-oublie" className="text-[12px] text-center" style={{ color: "var(--accent-ink)" }}>
              Demander un nouveau lien
            </Link>
            <Link to="/connexion" className="text-[12px] text-center" style={{ color: "var(--accent-ink)" }}>
              Retour à la connexion
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}

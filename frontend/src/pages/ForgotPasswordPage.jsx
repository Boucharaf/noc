import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import AuthLayout from "../components/layout/AuthLayout";
import { Notice } from "../components/ui/Controls";
import { auth } from "../api/noc";
import { errorMessage } from "../api/client";
import { clock } from "../hooks/useLoginLock";

/**
 * « Mot de passe oublié » (INC-45) : demande du lien de réinitialisation.
 *
 * La réponse du serveur est la même que le compte existe ou non ; l'écran ne
 * dit donc jamais si l'identifiant est connu.
 */
export default function ForgotPasswordPage() {
  const [identifier, setIdentifier] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [wait, setWait] = useState(0);
  const [support, setSupport] = useState(null);

  useEffect(() => {
    let alive = true;
    auth
      .support()
      .then((data) => alive && setSupport(data))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!wait) return undefined;
    const timer = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const noMail = support?.password_reset_by_email === false;

  const submit = async (event) => {
    event.preventDefault();
    if (!identifier.trim() || wait) return;
    setPending(true);
    setError(null);
    try {
      const data = await auth.requestPasswordReset(identifier.trim());
      setMessage(data?.message);
    } catch (failure) {
      const seconds = failure.response?.data?.detail?.retry_after_seconds;
      if (seconds) setWait(seconds);
      else setError(errorMessage(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <AuthLayout>
      <div style={{ padding: 24, color: "#4a5578", fontSize: 12, lineHeight: 1.5 }}>
        <h1 style={{ margin: "0 0 10px", fontSize: 16, fontWeight: 600, color: "#172238" }}>
          Mot de passe oublié
        </h1>
        {message ? (
          <Notice tone="success">{message}</Notice>
        ) : noMail ? (
          <Notice tone="warning">
            L'envoi de courriels n'est pas configuré sur ce serveur. Demandez au Chef NOC de
            réinitialiser votre mot de passe.
          </Notice>
        ) : (
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label htmlFor="reset-identifier">
              Saisissez votre identifiant ou votre adresse électronique : un lien pour choisir un
              nouveau mot de passe vous sera envoyé.
            </label>
            <input
              id="reset-identifier"
              className="input"
              value={identifier}
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="Identifiant ou adresse électronique"
              autoComplete="username"
              maxLength={254}
              autoFocus
              required
            />
            {wait > 0 && (
              <Notice tone="error">Trop de demandes. Réessayez dans {clock(wait)}.</Notice>
            )}
            {error && <Notice tone="error">{error}</Notice>}
            <button
              type="submit"
              className="btn btn-primary w-full"
              disabled={pending || wait > 0 || !identifier.trim()}
            >
              {pending ? "Envoi…" : "Recevoir un lien"}
            </button>
            <span style={{ color: "#5c6488" }}>
              Pas d'adresse sur votre compte, ou connexion par code PIN seulement ? Adressez-vous au
              Chef NOC.
            </span>
          </form>
        )}
        {(support?.email || support?.phone) && (
          <p style={{ margin: "10px 0 0" }}>
            <strong>Support NOC</strong>
            {support.email && (
              <> · <a href={`mailto:${support.email}`} style={{ color: "#006fa8" }}>{support.email}</a></>
            )}
            {support.phone && (
              <> · <a href={`tel:${support.phone.replace(/\s/g, "")}`} style={{ color: "#006fa8" }}>{support.phone}</a></>
            )}
            {support.hours && <span style={{ display: "block" }}>{support.hours}</span>}
          </p>
        )}
        <Link to="/connexion" style={{ display: "block", marginTop: 14, textAlign: "center", color: "#006fa8" }}>
          Retour à la connexion
        </Link>
      </div>
    </AuthLayout>
  );
}

import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Delete, Eye, EyeOff, KeyRound, Lock, User } from "lucide-react";

import AuthLayout from "../components/layout/AuthLayout";
import { Notice } from "../components/ui/Controls";
import { auth } from "../api/noc";
import { errorMessage } from "../api/client";
import { homeRoute } from "../lib/permissions";
import { clock, useLoginLock } from "../hooks/useLoginLock";
import { useAuthStore } from "../store/auth";
import { useScopeStore } from "../store/scope";
import { useWindowStore } from "../store/ui";

/**
 * Écran de connexion.
 *
 * Deux modes :
 * · identifiant + mot de passe, pour un poste personnel ;
 * · identifiant + code PIN, pour la relève d'équipe sur une console partagée en salle.
 *
 * Le fond utilise la carte du Burkina Faso avec un effet de flou et un
 * dégradé bleu vers le bas. Le formulaire est toujours affiché en thème
 * clair, quelle que soit la préférence de l'utilisateur.
 */
export default function LoginPage() {
  const token = useAuthStore((s) => s.token);
  const role = useAuthStore((s) => s.user?.role);
  const login = useAuthStore((s) => s.login);
  const logoutReason = useAuthStore((s) => s.logoutReason);
  const clearLogoutReason = useAuthStore((s) => s.clearLogoutReason);
  const navigate = useNavigate();

  // Attente imposée après trop de tentatives : reprend après actualisation.
  const { lock, remaining, start: startLock } = useLoginLock();
  const [mode, setMode] = useState(lock?.mode ?? "password");
  // INC-45 : recours en cas de blocage — contact du support, servi par le
  // backend (SUPPORT_EMAIL, SUPPORT_PHONE, SUPPORT_HOURS).
  const [helpOpen, setHelpOpen] = useState(false);
  const [support, setSupport] = useState(null);
  useEffect(() => {
    let alive = true;
    auth
      .support()
      .then((data) => alive && setSupport(data))
      .catch(() => alive && setSupport(null));
    return () => {
      alive = false;
    };
  }, []);
  const [username, setUsername] = useState(lock?.username ?? "");
  const [password, setPassword] = useState("");
  const passwordRef = useRef(null);
  const [showPassword, setShowPassword] = useState(false);
  const [pin, setPin] = useState("");
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (logoutReason === "expired") {
      setError("Votre session a expiré. Reconnectez-vous.");
      clearLogoutReason();
    } else if (logoutReason === "password_changed") {
      setError("Mot de passe modifié. Reconnectez-vous avec le nouveau mot de passe.");
      clearLogoutReason();
    }
  }, [logoutReason, clearLogoutReason]);

  // Le verrou vise un compte : un collègue peut se connecter avec le sien sur
  // la même console. Une adresse verrouillée, elle, est refusée par le serveur.
  const locked =
    remaining > 0 &&
    lock?.mode === mode &&
    lock.username.toLowerCase() === username.trim().toLowerCase();

  if (token) return <Navigate to={homeRoute(role)} replace />;

  const submit = async (event) => {
    event?.preventDefault();
    if (locked) return;
    setError(null);
    setPending(true);
    try {
      const data =
        mode === "password"
          ? await auth.login(username.trim(), password)
          : await auth.pinLogin(username.trim(), pin);
      // INC-30 : une nouvelle connexion repart de « Tout le réseau » et de la
      // période par défaut — jamais des filtres de la session précédente,
      // qui feraient lire les chiffres d'un autre périmètre sans le savoir.
      useScopeStore.getState().reset();
      useWindowStore.getState().setHours(24);
      login(data.access_token, data.user, data.expires_in);
      navigate(homeRoute(data.user.role), { replace: true });
    } catch (loginError) {
      const detail = loginError.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.retry_after_seconds) {
        startLock(username.trim(), mode, detail.retry_after_seconds);
      } else {
        setError(
          loginError.isNetworkError
            ? "Vérifier la connexion"
            : errorMessage(loginError, "Identifiants incorrects."),
        );
      }
      // Refus du serveur : le champ secret se vide, l'identifiant reste. Une
      // coupure réseau ne dit rien du mot de passe : il est conservé.
      if (loginError.response) {
        setPassword("");
        setPin("");
      }
      setPending(false);
      setTimeout(() => passwordRef.current?.focus(), 0);
    }
  };

  const pressDigit = (digit) => {
    if (locked || pin.length >= 6) return;
    setPin(pin + digit);
  };

  return (
    <AuthLayout>
          {/* Onglets */}
          <div
            style={{
              display: "flex",
              borderBottom: "1px solid rgba(34, 101, 172, 0.15)",
            }}
            role="tablist"
            aria-label="Mode de connexion"
          >
            {[
              { value: "password", label: "Mot de passe", icon: Lock },
              { value: "pin", label: "Code PIN", icon: KeyRound },
            ].map((tab) => {
              const Icon = tab.icon;
              const active = mode === tab.value;
              return (
                <button
                  key={tab.value}
                  type="button"
                  // INC-44 : l'onglet actif est porté par aria-selected, et le
                  // soulignement suit exactement le même état.
                  role="tab"
                  aria-selected={active}
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                    height: 36,
                    fontSize: 12,
                    fontWeight: 500,
                    fontFamily: "inherit",
                    border: "none",
                    borderBottom: `2px solid ${active ? "#0e7ec2" : "transparent"}`,
                    marginBottom: -1,
                    cursor: "pointer",
                    color: active ? "#0e7ec2" : "#718096",
                    background: active ? "#e8f3fb" : "#f1f3f6",
                    transition: "all 0.15s ease",
                  }}
                  onClick={() => {
                    setMode(tab.value);
                    setError(null);
                  }}
                >
                  <Icon size={13} />
                  {tab.label}
                </button>
              );
            })}
          </div>

          {/* Corps du formulaire */}
          <form
            onSubmit={submit}
            style={{ padding: "20px 24px 24px", display: "flex", flexDirection: "column", gap: 14 }}
          >
            {locked ? (
              <div role="timer" aria-live="off">
                <Notice tone="error">
                  Trop de tentatives. Réessayez dans <strong className="num">{clock(remaining)}</strong>.
                </Notice>
              </div>
            ) : (
              error && <Notice tone="error">{error}</Notice>
            )}

            {mode === "password" ? (
              <>
                <p style={{ fontSize: 12, color: "#52627a", margin: 0 }}>
                  Entrez votre identifiant et votre mot de passe pour continuer.
                </p>

                <label style={{ display: "block" }}>
                  <span
                    style={{
                      display: "block",
                      fontSize: 12,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      color: "#52627a",
                      marginBottom: 4,
                    }}
                  >
                    Identifiant
                  </span>
                  <div style={{ position: "relative" }}>
                    <User
                      size={13}
                      style={{
                        position: "absolute",
                        left: 10,
                        top: "50%",
                        transform: "translateY(-50%)",
                        color: "#718096",
                      }}
                    />
                    <input
                      className="login-input"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      autoComplete="username"
                      autoFocus
                      required
                    />
                  </div>
                </label>

                <label style={{ display: "block" }}>
                  <span
                    style={{
                      display: "block",
                      fontSize: 12,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      color: "#52627a",
                      marginBottom: 4,
                    }}
                  >
                    Mot de passe
                  </span>
                  <div style={{ position: "relative" }}>
                    <Lock
                      size={13}
                      style={{
                        position: "absolute",
                        left: 10,
                        top: "50%",
                        transform: "translateY(-50%)",
                        color: "#718096",
                      }}
                    />
                    <input
                      className="login-input"
                      style={{ paddingRight: 40 }}
                      ref={passwordRef}
                      disabled={locked}
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      autoComplete="current-password"
                      required
                    />
                    <button
                      type="button"
                      style={{
                        position: "absolute",
                        right: 10,
                        top: "50%",
                        transform: "translateY(-50%)",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        color: "#718096",
                        padding: 0,
                        display: "flex",
                      }}
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                    >
                      {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  </div>
                </label>

                <button
                  type="submit"
                  style={{
                    ...submitBtnStyle,
                    opacity: locked || pending || !username || !password ? 0.55 : 1,
                    cursor: locked || pending || !username || !password ? "not-allowed" : "pointer",
                  }}
                  disabled={locked || pending || !username || !password}
                >
                  {pending ? "Connexion…" : "Se connecter"}
                </button>
              </>
            ) : (
              <>
                {/* INC-43 : le PIN n'est accepté que sur un poste reconnu. */}
                <p style={{ fontSize: 12, color: "#52627a", margin: 0 }}>
                  Le code PIN fonctionne sur les postes où un identifiant et un mot de passe ont
                  déjà été saisis au moins une fois.
                </p>
                <label style={{ display: "block" }}>
                  <span
                    style={{
                      display: "block",
                      fontSize: 12,
                      fontWeight: 600,
                      letterSpacing: "0.06em",
                      textTransform: "uppercase",
                      color: "#52627a",
                      marginBottom: 4,
                    }}
                  >
                    Identifiant
                  </span>
                  <input
                    className="login-input"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    required
                  />
                </label>
                {/* indicateur PIN */}
                <div
                  style={{ display: "flex", justifyContent: "center", gap: 8 }}
                  aria-label="Code saisi"
                >
                  {Array.from({ length: 6 }).map((_, index) => (
                    <span
                      key={index}
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: index < pin.length ? "#0e7ec2" : "#d1dde8",
                        display: "inline-block",
                      }}
                    />
                  ))}
                </div>

                {/* Pavé numérique */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}>
                  {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((digit) => (
                    <button
                      key={digit}
                      type="button"
                      style={pinBtnStyle}
                      onClick={() => pressDigit(digit)}
                    >
                      {digit}
                    </button>
                  ))}
                  <button
                    type="button"
                    style={{ ...pinBtnStyle, fontSize: 12 }}
                    onClick={() => setPin("")}
                    aria-label="Effacer"
                  >
                    C
                  </button>
                  <button
                    type="button"
                    style={pinBtnStyle}
                    onClick={() => pressDigit("0")}
                  >
                    0
                  </button>
                  <button
                    type="button"
                    style={{ ...pinBtnStyle, fontSize: 12 }}
                    onClick={() => setPin(pin.slice(0, -1))}
                    aria-label="Corriger"
                  >
                    <Delete size={15} />
                  </button>
                </div>

                <button
                  type="submit"
                  style={{
                    ...submitBtnStyle,
                    opacity: locked || pending || pin.length < 4 || !username.trim() ? 0.55 : 1,
                    cursor: locked || pending || pin.length < 4 || !username.trim() ? "not-allowed" : "pointer",
                  }}
                  disabled={locked || pending || pin.length < 4 || !username.trim()}
                >
                  {pending ? "Vérification…" : "Valider"}
                </button>
              </>
            )}
          </form>

          {/* INC-45 : « Mot de passe oublié » et contact du support. */}
          <div style={{ padding: "0 24px 18px", fontSize: 12, color: "#4a5578" }}>
            {mode === "password" ? (
              <Link to="/mot-de-passe-oublie" style={{ color: "#006fa8" }}>
                Mot de passe oublié ?
              </Link>
            ) : (
            <button
              type="button"
              onClick={() => setHelpOpen((open) => !open)}
              aria-expanded={helpOpen}
              style={{
                border: "none",
                background: "none",
                padding: 0,
                color: "#006fa8",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: 12,
                textDecoration: "underline",
              }}
            >
              Code PIN oublié ou bloqué ?
            </button>
            )}
            {mode === "pin" && helpOpen && (
              <div
                role="region"
                aria-label="Aide à la connexion"
                style={{
                  marginTop: 8,
                  padding: "8px 10px",
                  borderRadius: 6,
                  background: "#eef4fb",
                  lineHeight: 1.5,
                }}
              >
                <p style={{ margin: 0 }}>
                  Le code PIN est réinitialisé par un administrateur du NOC (Chef NOC), qui vous
                  communique un nouveau code.
                </p>
                {support?.email || support?.phone ? (
                  <p style={{ margin: "6px 0 0" }}>
                    <strong>Support NOC</strong>
                    {support.email && (
                      <>
                        {" "}· <a href={`mailto:${support.email}`} style={{ color: "#006fa8" }}>{support.email}</a>
                      </>
                    )}
                    {support.phone && (
                      <>
                        {" "}· <a href={`tel:${support.phone.replace(/\s/g, "")}`} style={{ color: "#006fa8" }}>{support.phone}</a>
                      </>
                    )}
                    {support.hours && <span style={{ display: "block" }}>{support.hours}</span>}
                  </p>
                ) : (
                  <p style={{ margin: "6px 0 0" }}>Adressez-vous à votre responsable ou au Chef NOC.</p>
                )}
              </div>
            )}
          </div>
    </AuthLayout>
  );
}

/* ---------- styles inline partagés ---------- */

const submitBtnStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: "100%",
  height: 42,
  borderRadius: 6,
  border: "none",
  background: "linear-gradient(135deg, #1a9ad9 0%, #0d6fb0 100%)",
  color: "#fff",
  fontSize: 13.5,
  fontWeight: 600,
  fontFamily: "inherit",
  letterSpacing: "0.02em",
  cursor: "pointer",
  transition: "filter 0.15s ease",
  boxShadow: "0 2px 8px rgba(13, 111, 176, 0.35)",
};

const pinBtnStyle = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: 40,
  borderRadius: 6,
  border: "1px solid #cdd6e0",
  background: "#eef2f6",
  color: "#172238",
  fontSize: 17,
  fontFamily: "inherit",
  cursor: "pointer",
  transition: "background 0.12s ease",
};

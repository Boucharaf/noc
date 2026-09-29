import { useEffect, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Delete, Eye, EyeOff, KeyRound, Lock, User } from "lucide-react";

import { Notice } from "../components/ui/Controls";
import { auth } from "../api/noc";
import { errorMessage } from "../api/client";
import { homeRoute } from "../lib/permissions";
import { useAuthStore } from "../store/auth";

/**
 * Écran de connexion.
 *
 * Deux modes :
 * · identifiant + mot de passe, pour un poste personnel ;
 * · code PIN, pour la relève d'équipe sur une console partagée en salle.
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

  const [mode, setMode] = useState("password");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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

  if (token) return <Navigate to={homeRoute(role)} replace />;

  const submit = async (event) => {
    event?.preventDefault();
    setError(null);
    setPending(true);
    try {
      const data =
        mode === "password"
          ? await auth.login(username.trim(), password)
          : await auth.pinLogin(pin);
      login(data.access_token, data.user, data.expires_in);
      navigate(homeRoute(data.user.role), { replace: true });
    } catch (loginError) {
      const detail = loginError.response?.data?.detail;
      if (detail && typeof detail === "object" && detail.retry_after_seconds) {
        setError(
          `Trop de tentatives. Réessayez dans ${Math.ceil(detail.retry_after_seconds / 60)} minute(s).`,
        );
      } else {
        setError(
          loginError.isNetworkError
            ? "Vérifier la connexion"
            : errorMessage(loginError, "Identifiants incorrects."),
        );
      }
      setPin("");
      setPending(false);
    }
  };

  const pressDigit = (digit) => {
    if (pin.length >= 6) return;
    setPin(pin + digit);
  };

  return (
    /* Conteneur plein écran avec fond carte du BF */
    <div
      style={{
        position: "relative",
        minHeight: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "24px 16px",
        overflow: "hidden",
      }}
    >
      {/* Image de fond */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: "url(/carte_du_BF.jpg)",
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: "blur(5px)",
          transform: "scale(1.06)", /* évite les bords blancs du blur */
          zIndex: 0,
        }}
      />

      {/* Dégradé bleu vers le bas, par-dessus l'image floutée */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(to bottom, rgba(20, 60, 120, 0.38) 0%, rgba(10, 35, 90, 0.72) 100%)",
          zIndex: 1,
        }}
      />

      {/* Formulaire centré — thème clair forcé */}
      <div
        className="light"
        style={{
          position: "relative",
          zIndex: 2,
          width: "100%",
          maxWidth: 380,
        }}
      >
        {/* En-tête avec logo */}
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <img
            src="/images.png"
            alt="ANPTIC"
            style={{
              height: 56,
              width: "auto",
              objectFit: "contain",
              display: "inline-block",
              filter: "drop-shadow(0 2px 8px rgba(0,0,0,0.4))",
            }}
          />
        </div>

        {/* Carte du formulaire */}
        <div
          style={{
            background: "rgba(245, 247, 249, 0.97)",
            borderRadius: 12,
            boxShadow:
              "0 8px 40px rgba(10, 35, 90, 0.28), 0 2px 8px rgba(0,0,0,0.12)",
            overflow: "hidden",
            border: "1px solid rgba(34, 101, 172, 0.15)",
          }}
        >
          {/* Onglets */}
          <div
            style={{
              display: "flex",
              borderBottom: "1px solid rgba(34, 101, 172, 0.15)",
            }}
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
            {error && <Notice tone="error">{error}</Notice>}

            {mode === "password" ? (
              <>
                <p style={{ fontSize: 12, color: "#52627a", margin: 0 }}>
                  Entrez votre identifiant et votre mot de passe pour continuer.
                </p>

                <label style={{ display: "block" }}>
                  <span
                    style={{
                      display: "block",
                      fontSize: 10.5,
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
                      fontSize: 10.5,
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
                    opacity: pending || !username || !password ? 0.55 : 1,
                    cursor: pending || !username || !password ? "not-allowed" : "pointer",
                  }}
                  disabled={pending || !username || !password}
                >
                  {pending ? "Connexion…" : "Se connecter"}
                </button>
              </>
            ) : (
              <>
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
                    opacity: pending || pin.length < 4 ? 0.55 : 1,
                    cursor: pending || pin.length < 4 ? "not-allowed" : "pointer",
                  }}
                  disabled={pending || pin.length < 4}
                >
                  {pending ? "Vérification…" : "Valider"}
                </button>
              </>
            )}
          </form>
        </div>
      </div>
    </div>
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

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
 * Deux modes, parce qu'il y a deux contextes d'usage réels :
 *
 * · identifiant + mot de passe, pour un poste personnel ;
 * · code PIN, pour la relève d'équipe sur une console partagée en salle.
 *   Le backend ne l'autorise QU'aux agents terrain
 *   (routes/auth.py::PIN_LOGIN_ALLOWED_ROLES) : un compte directeur ou
 *   chef NOC porte trop de privilèges pour un facteur à quatre chiffres.
 *   Le pavé numérique s'utilise au doigt sur une tablette, gants compris.
 *
 * L'écran affiche l'heure : sur une console de salle, c'est aussi
 * l'horloge murale.
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
      // Posé par « Mon compte » : le backend a fermé toutes les sessions.
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
      // Le verrouillage par IP renvoie un objet `detail` structuré ;
      // errorMessage() ne saurait pas le lire.
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
    <div
      className="h-full flex items-center justify-center p-4"
      style={{
        background:
          "radial-gradient(1100px 520px at 50% -10%, color-mix(in srgb, var(--accent) 12%, transparent), transparent), var(--page)",
      }}
    >
      <div className="w-full" style={{ maxWidth: 460 }}>
        <div className="text-center mb-5">
          <div className="flex items-center justify-center gap-2 mb-1">
            <span className="live-dot" />
            <h1 className="text-[19px] font-semibold tracking-tight">NOC RESINA</h1>
          </div>
        </div>

        <div
          className="panel"
          style={{ minHeight: 410, boxShadow: "0 24px 64px rgba(0,0,0,.35)" }}
        >
          <div className="flex border-b" style={{ borderColor: "var(--border)" }}>
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
                  className="flex-1 flex items-center justify-center gap-1.5 text-[12px] font-medium border-b-2 -mb-px"
                  style={{
                    height: 34,
                    color: active ? "var(--ink)" : "var(--ink-3)",
                    borderColor: active ? "var(--accent)" : "transparent",
                    background: active ? "var(--surface)" : "var(--surface-2)",
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

          <form onSubmit={submit} className="p-6 space-y-4">
            {error && <Notice tone="error">{error}</Notice>}

            {mode === "password" ? (
              <>
                <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
                  Entrez votre identifiant et votre mot de passe pour continuer.
                </p>
                <label className="block">
                  <span className="field-label">Identifiant</span>
                  <div className="relative">
                    <User
                      size={13}
                      className="absolute left-2 top-1/2 -translate-y-1/2"
                      style={{ color: "var(--ink-3)" }}
                    />
                    <input
                      className="input"
                      style={{ paddingLeft: 24, minHeight: 42 }}
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      autoComplete="username"
                      autoFocus
                      required
                    />
                  </div>
                </label>
                <label className="block">
                  <span className="field-label">Mot de passe</span>
                  <div className="relative">
                    <Lock
                      size={13}
                      className="absolute left-2 top-1/2 -translate-y-1/2"
                      style={{ color: "var(--ink-3)" }}
                    />
                    <input
                      className="input"
                      style={{ paddingLeft: 24, paddingRight: 40, minHeight: 42 }}
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                      required
                    />
                    <button
                      type="button"
                      className="absolute right-2 top-1/2 -translate-y-1/2"
                      style={{ color: "var(--ink-3)" }}
                      onClick={() => setShowPassword((visible) => !visible)}
                      aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                      title={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                    >
                      {showPassword ? <EyeOff size={15} /> : <Eye size={15} />}
                    </button>
                  </div>
                </label>
                <button
                  type="submit"
                  className="btn btn-primary w-full"
                  style={{ minHeight: 42 }}
                  disabled={pending || !username || !password}
                >
                  {pending ? "Connexion…" : "Se connecter"}
                </button>
              </>
            ) : (
              <>
                <div className="flex justify-center gap-2 my-2" aria-label="Code saisi">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <span
                      key={index}
                      className="rounded-full"
                      style={{
                        width: 10,
                        height: 10,
                        background: index < pin.length ? "var(--accent)" : "var(--surface-3)",
                      }}
                    />
                  ))}
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((digit) => (
                    <button
                      key={digit}
                      type="button"
                      className="btn num"
                      style={{ height: 40, fontSize: 16 }}
                      onClick={() => pressDigit(digit)}
                    >
                      {digit}
                    </button>
                  ))}
                  <button
                    type="button"
                    className="btn"
                    style={{ height: 40 }}
                    onClick={() => setPin("")}
                    aria-label="Effacer"
                  >
                    C
                  </button>
                  <button
                    type="button"
                    className="btn num"
                    style={{ height: 40, fontSize: 16 }}
                    onClick={() => pressDigit("0")}
                  >
                    0
                  </button>
                  <button
                    type="button"
                    className="btn"
                    style={{ height: 40 }}
                    onClick={() => setPin(pin.slice(0, -1))}
                    aria-label="Corriger"
                  >
                    <Delete size={15} />
                  </button>
                </div>
                <button
                  type="submit"
                  className="btn btn-primary w-full"
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

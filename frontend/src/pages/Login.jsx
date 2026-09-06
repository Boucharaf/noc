import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Delete, Lock, User } from "lucide-react";
import { loginWithPassword, loginWithPin } from "../api/auth";
import { useAuthStore } from "../store/auth";
import { getHomeRoute } from "../utils/roleHome";
import Logo from "../components/Logo";

const PIN_LENGTH = 4;

const PasswordForm = ({ onSubmit, loading, error }) => {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit(() => loginWithPassword(username, password));
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label
          className="mb-1.5 block text-xs font-semibold uppercase tracking-wide"
          style={{ color: "var(--color-text-secondary)" }}
        >
          Identifiant
        </label>
        <div
          className="flex items-center gap-2 rounded-lg border px-3 py-2.5"
          style={{
            borderColor: "var(--color-border-strong)",
            background: "var(--color-surface-2)",
          }}
        >
          <User
            className="h-4 w-4"
            style={{ color: "var(--color-text-muted)" }}
          />
          <input
            autoFocus
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="identifiant"
            className="w-full bg-transparent text-sm outline-none"
            style={{ color: "var(--color-text-primary)" }}
          />
        </div>
      </div>
      <div>
        <label
          className="mb-1.5 block text-xs font-semibold uppercase tracking-wide"
          style={{ color: "var(--color-text-secondary)" }}
        >
          Mot de passe
        </label>
        <div
          className="flex items-center gap-2 rounded-lg border px-3 py-2.5"
          style={{
            borderColor: "var(--color-border-strong)",
            background: "var(--color-surface-2)",
          }}
        >
          <Lock
            className="h-4 w-4"
            style={{ color: "var(--color-text-muted)" }}
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="w-full bg-transparent text-sm outline-none"
            style={{ color: "var(--color-text-primary)" }}
          />
        </div>
      </div>

      {error && (
        <p
          className="text-sm font-medium"
          style={{ color: "var(--color-critical, #d03b3b)" }}
        >
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={loading || !username || !password}
        className="w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
        style={{ background: "var(--color-accent)" }}
      >
        {loading ? "Connexion…" : "Se connecter"}
      </button>
    </form>
  );
};

const PinForm = ({ onSubmit, loading, error }) => {
  const [pin, setPin] = useState("");

  const pushDigit = (digit) => {
    if (loading) return;
    const next = (pin + digit).slice(0, PIN_LENGTH);
    setPin(next);
    if (next.length === PIN_LENGTH) {
      onSubmit(() => loginWithPin(next)).finally(() => setPin(""));
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex justify-center gap-3">
        {Array.from({ length: PIN_LENGTH }).map((_, i) => (
          <span
            key={i}
            className="h-3.5 w-3.5 rounded-full border-2 transition-colors"
            style={{
              borderColor: "var(--color-accent)",
              background:
                i < pin.length ? "var(--color-accent)" : "transparent",
            }}
          />
        ))}
      </div>

      {error && (
        <p
          className="text-center text-sm font-medium"
          style={{ color: "var(--color-critical, #d03b3b)" }}
        >
          {error}
        </p>
      )}

      <div className="mx-auto grid max-w-[240px] grid-cols-3 gap-3">
        {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
          <button
            key={n}
            type="button"
            disabled={loading}
            onClick={() => pushDigit(String(n))}
            className="rounded-xl border py-3 text-lg font-semibold transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
            style={{
              borderColor: "var(--color-border-strong)",
              color: "var(--color-text-primary)",
            }}
          >
            {n}
          </button>
        ))}
        <div />
        <button
          type="button"
          disabled={loading}
          onClick={() => pushDigit("0")}
          className="rounded-xl border py-3 text-lg font-semibold transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
          style={{
            borderColor: "var(--color-border-strong)",
            color: "var(--color-text-primary)",
          }}
        >
          0
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={() => setPin((p) => p.slice(0, -1))}
          className="flex items-center justify-center rounded-xl border py-3 transition-colors hover:bg-[var(--color-surface-2)] disabled:opacity-50"
          style={{
            borderColor: "var(--color-border-strong)",
            color: "var(--color-text-muted)",
          }}
        >
          <Delete className="h-5 w-5" />
        </button>
      </div>
    </div>
  );
};

const Login = () => {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const logoutReason = useAuthStore((s) => s.logoutReason);
  const clearLogoutReason = useAuthStore((s) => s.clearLogoutReason);
  const [mode, setMode] = useState("password");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (logoutReason === "expired") {
      setError("Session expirée — veuillez vous reconnecter.");
      clearLogoutReason();
    }
  }, [logoutReason, clearLogoutReason]);

  const handleSubmit = (request) => {
    setLoading(true);
    setError(null);
    return request()
      .then((data) => {
        login(data.access_token, data.user, data.expires_in);
        navigate(getHomeRoute(data.user?.role), { replace: true });
      })
      .catch((err) => {
        setError(err.response?.data?.detail ?? "Échec de la connexion");
      })
      .finally(() => setLoading(false));
  };

  return (
    <div
      className="flex min-h-screen items-center justify-center p-4"
      style={{ background: "var(--color-page)" }}
    >
      <div
        className="w-full max-w-sm rounded-2xl border p-8"
        style={{
          background: "var(--color-surface)",
          borderColor: "var(--color-border)",
          boxShadow: "var(--shadow-elevate)",
        }}
      >
        <div className="mb-6 flex flex-col items-center text-center">
          <Logo size={56} className="mb-3" />
          <h1
            className="text-lg font-bold"
            style={{ color: "var(--color-text-primary)" }}
          >
            NOC
          </h1>
          <p
            className="text-sm"
            style={{ color: "var(--color-text-secondary)" }}
          >
            Centre des Opérations Réseau
          </p>
        </div>

        <div
          className="mb-6 flex rounded-lg border p-1"
          style={{ borderColor: "var(--color-border)" }}
        >
          {[
            ["password", "Mot de passe"],
            ["pin", "Code PIN"],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => {
                setMode(key);
                setError(null);
              }}
              className="flex-1 rounded-md py-1.5 text-sm font-medium transition-colors"
              style={{
                background:
                  mode === key ? "var(--color-accent-soft)" : "transparent",
                color:
                  mode === key
                    ? "var(--color-accent)"
                    : "var(--color-text-secondary)",
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === "password" ? (
          <PasswordForm
            onSubmit={handleSubmit}
            loading={loading}
            error={error}
          />
        ) : (
          <PinForm onSubmit={handleSubmit} loading={loading} error={error} />
        )}
      </div>
    </div>
  );
};

export default Login;

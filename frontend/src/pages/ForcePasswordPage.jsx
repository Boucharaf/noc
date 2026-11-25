import { useNavigate } from "react-router-dom";

import { Notice } from "../components/ui/Controls";
import { auth } from "../api/noc";
import { useAuthStore } from "../store/auth";
import { PasswordPanel } from "./AccountPage";

/**
 * Mot de passe provisoire : à changer avant tout le reste (A01).
 *
 * Affiché à la place de l'application tant que le compte porte un mot de
 * passe choisi par quelqu'un d'autre. Le backend refuse de toute façon les
 * autres routes (dependencies/auth.py).
 */
export default function ForcePasswordPage() {
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  const leave = async (reason = null) => {
    try {
      await auth.logout();
    } catch {
      /* session déjà fermée côté serveur */
    }
    logout(reason);
    navigate("/connexion", { replace: true });
  };

  return (
    <div className="min-h-full flex items-center justify-center p-4">
      <div className="w-full space-y-2.5" style={{ maxWidth: 420 }}>
        <Notice tone="warning">
          Votre mot de passe est provisoire. Choisissez le vôtre pour accéder au NOC.
        </Notice>
        <PasswordPanel onChanged={() => leave("password_changed")} />
        <button type="button" className="btn btn-sm" onClick={() => leave()}>
          Se déconnecter
        </button>
      </div>
    </div>
  );
}

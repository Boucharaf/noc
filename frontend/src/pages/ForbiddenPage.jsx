import { Link } from "react-router-dom";
import { ShieldOff } from "lucide-react";

import { ROLE_DESCRIPTION, ROLE_LABEL, homeRoute } from "../lib/permissions";
import { useCurrentUser } from "../hooks/useSession";

/**
 * Écran d'accès refusé.
 *
 * Dit POURQUOI l'accès est refusé et OÙ aller ensuite. Une page « 403 »
 * sèche pousse l'utilisateur à signaler un bug alors que le
 * comportement est correct : chaque profil n'a pas les mêmes écrans, et
 * c'est le principe même de l'application.
 */
export default function ForbiddenPage() {
  const user = useCurrentUser();

  return (
    <div className="flex flex-col items-center justify-center text-center py-16 gap-2">
      <ShieldOff size={26} strokeWidth={1.5} style={{ color: "var(--ink-3)" }} />
      <h1 className="text-[16px] font-semibold">Écran non accessible à votre profil</h1>
      <p className="text-[12.5px] max-w-[52ch]" style={{ color: "var(--ink-2)" }}>
        Vous êtes connecté en tant que{" "}
        <strong>{ROLE_LABEL[user?.role] ?? user?.role}</strong>.{" "}
        {ROLE_DESCRIPTION[user?.role]}
      </p>
      <p className="text-[11.5px] max-w-[52ch]" style={{ color: "var(--ink-3)" }}>
        Si vous avez besoin de cet écran, demandez au Chef NOC ou au Directeur de faire
        évoluer votre rôle depuis la gestion des comptes.
      </p>
      <Link to={homeRoute(user?.role)} className="btn btn-sm btn-primary mt-2">
        Revenir à mon tableau de bord
      </Link>
    </div>
  );
}

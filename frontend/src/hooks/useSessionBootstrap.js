import { useEffect } from "react";
import { useAuthStore } from "../store/auth";

// À appeler une seule fois près de la racine de l'app (ex. dans App.jsx,
// avant le rendu des routes protégées). Comme le token n'est plus persisté
// en localStorage (voir store/auth.js), la session doit être reconstituée à
// chaque chargement de page à partir du cookie httpOnly de refresh — c'est
// le rôle de bootstrap(). Tant que `bootstrapped` est false, affichez un
// loader plutôt que de rediriger vers /login : sinon un utilisateur avec une
// session valide voit un flash de l'écran de connexion à chaque F5.
export const useSessionBootstrap = () => {
  const bootstrapped = useAuthStore((s) => s.bootstrapped);

  useEffect(() => {
    useAuthStore.getState().bootstrap();
  }, []);

  return bootstrapped;
};
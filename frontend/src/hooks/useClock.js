import { useEffect, useState } from "react";

/**
 * Horloge de salle.
 *
 * Battement à la seconde et non à la minute : sur un mur d'écrans, une
 * horloge dont les secondes défilent est la preuve visuelle la plus
 * simple que l'interface n'est pas figée. Un dashboard gelé sur une
 * valeur ancienne est le pire mode de panne d'un NOC — il ne se voit pas.
 */
export function useClock() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    // Aligné sur la seconde suivante plutôt qu'un setInterval(1000) lancé
    // à un instant arbitraire : sinon l'affichage saute de 14:59:58 à
    // 15:00:00 selon la dérive du timer.
    let timer;
    const tick = () => {
      const date = new Date();
      setNow(date);
      timer = setTimeout(tick, 1000 - date.getMilliseconds());
    };
    tick();
    return () => clearTimeout(timer);
  }, []);

  return now;
}

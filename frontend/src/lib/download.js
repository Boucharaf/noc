/**
 * Téléchargement d'un Blob renvoyé par l'API.
 *
 * Deux détails qui ont chacun coûté un bug :
 *
 * 1. `revokeObjectURL` est indispensable. Sans lui, chaque export garde
 *    son contenu en mémoire jusqu'au rechargement de l'onglet — sur un
 *    poste de supervision qui reste ouvert des semaines, un rapport PDF
 *    de 4 Mo téléchargé chaque matin finit par peser.
 * 2. Quand le backend échoue, il renvoie du JSON avec le même
 *    `responseType: "blob"` demandé : le fichier téléchargé serait un
 *    « rapport.pdf » contenant `{"detail": "..."}`. On inspecte donc le
 *    type MIME avant d'enregistrer, et on relaie le message d'erreur.
 */

export async function saveBlob(blob, filename) {
  if (blob && blob.type && blob.type.includes("application/json")) {
    const text = await blob.text();
    let detail = "Le fichier n'a pas pu être généré.";
    try {
      detail = JSON.parse(text).detail || detail;
    } catch {
      // Réponse non-JSON malgré le type annoncé : on garde le message
      // par défaut plutôt que d'afficher du charabia.
    }
    throw new Error(detail);
  }

  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

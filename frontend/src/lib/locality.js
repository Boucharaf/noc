/**
 * Clé de comparaison d'un nom de lieu, miroir de
 * integrations/normalize.py::locality_key : « KUILSÉ », « Kuilsé » et
 * « KUILSE » désignent la même région selon la source.
 */
export function localityKey(name) {
  if (!name) return "";
  return String(name)
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toUpperCase();
}

/** Libellés des niveaux de désagrégation. */
export const LEVEL = {
  region: { label: "Région", plural: "Régions", child: "province" },
  province: { label: "Province", plural: "Provinces", child: "site" },
  site: { label: "Site", plural: "Sites", child: "node" },
  node: { label: "Équipement", plural: "Équipements", child: null },
};

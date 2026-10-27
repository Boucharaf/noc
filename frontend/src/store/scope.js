import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Périmètre consulté : recherche libre et localité (région > province > site).
 *
 * UN SEUL PÉRIMÈTRE POUR TOUS LES TABLEAUX DE BORD. Choisir « Guiriko » sur
 * la vue d'ensemble puis ouvrir l'écran SLA doit montrer les SLA de Guiriko,
 * pas ceux du pays : la barre de périmètre (ScopeBar) écrit ici, et chaque
 * requête lit ici. Le backend applique la même règle partout
 * (app/services/geo_service.py).
 *
 * La CASCADE est garantie à l'écriture : changer de région efface province
 * et site, sans quoi « Kadiogo > Houet » désignerait un lieu qui n'existe pas
 * et chaque écran serait vide sans dire pourquoi.
 *
 * Persisté par poste : un directeur régional rouvre sur sa région.
 */
export const useScopeStore = create(
  persist(
    (set) => ({
      region: null,
      province: null,
      site: null,
      search: "",

      setRegion: (region) => set({ region: region || null, province: null, site: null }),
      setProvince: (province) => set({ province: province || null, site: null }),
      setSite: (site) => set({ site: site || null }),
      setSearch: (search) => set({ search: search ?? "" }),
      /** Positionne tout le chemin d'un coup (fil d'Ariane, clic sur une carte). */
      setPath: ({ region = null, province = null, site = null }) =>
        set({ region, province, site }),
      reset: () => set({ region: null, province: null, site: null, search: "" }),
    }),
    {
      name: "noc-scope",
      partialize: (s) => ({ region: s.region, province: s.province, site: s.site }),
    },
  ),
);

/** Paramètres d'API du périmètre courant (clés absentes quand non filtré). */
export function scopeParams({ region, province, site, search }) {
  const params = {};
  if (region) params.region = region;
  if (province) params.province = province;
  if (site) params.site = site;
  if (search && search.trim()) params.search = search.trim();
  return params;
}

export function useScopeParams() {
  const region = useScopeStore((s) => s.region);
  const province = useScopeStore((s) => s.province);
  const site = useScopeStore((s) => s.site);
  const search = useScopeStore((s) => s.search);
  return scopeParams({ region, province, site, search });
}

/** Libellé court du périmètre : « Guiriko › Houet › Bobo-Dioulasso ». */
export function scopeLabel({ region, province, site }) {
  return [region, province, site].filter(Boolean).join(" › ") || "Tout le réseau";
}

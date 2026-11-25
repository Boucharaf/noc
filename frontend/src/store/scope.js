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
 * ORGANISATION et TYPE font partie du même périmètre (AM-30, INC-28) : une
 * seule barre de filtres, appliquée par le backend comme la localité
 * (geo_service.scope_nodes). Il n'y a plus de filtre propre à une page.
 *
 * Persisté par poste : un directeur régional rouvre sur sa région.
 */
export const useScopeStore = create(
  persist(
    (set) => ({
      region: null,
      province: null,
      site: null,
      organisation: null,
      nodeType: null,
      search: "",

      setOrganisation: (organisation) => set({ organisation: organisation || null }),
      setNodeType: (nodeType) => set({ nodeType: nodeType || null }),
      setRegion: (region) => set({ region: region || null, province: null, site: null }),
      setProvince: (province) => set({ province: province || null, site: null }),
      setSite: (site) => set({ site: site || null }),
      setSearch: (search) => set({ search: search ?? "" }),
      /** Positionne tout le chemin d'un coup (fil d'Ariane, clic sur une carte). */
      setPath: ({ region = null, province = null, site = null }) =>
        set({ region, province, site }),
      reset: () =>
        set({
          region: null,
          province: null,
          site: null,
          organisation: null,
          nodeType: null,
          search: "",
        }),
    }),
    {
      name: "noc-scope",
      partialize: (s) => ({
        region: s.region,
        province: s.province,
        site: s.site,
        organisation: s.organisation,
        nodeType: s.nodeType,
      }),
    },
  ),
);

/** Paramètres d'API du périmètre courant (clés absentes quand non filtré). */
export function scopeParams({ region, province, site, organisation, nodeType, search }) {
  const params = {};
  if (region) params.region = region;
  if (province) params.province = province;
  if (site) params.site = site;
  if (organisation) params.organisation = organisation;
  if (nodeType) params.node_type = nodeType;
  if (search && search.trim()) params.search = search.trim();
  return params;
}

export function useScopeParams() {
  const region = useScopeStore((s) => s.region);
  const province = useScopeStore((s) => s.province);
  const site = useScopeStore((s) => s.site);
  const organisation = useScopeStore((s) => s.organisation);
  const nodeType = useScopeStore((s) => s.nodeType);
  const search = useScopeStore((s) => s.search);
  return scopeParams({ region, province, site, organisation, nodeType, search });
}

/** Paramètres de LOCALITÉ seule, pour les agrégats journaliers et le journal
 * historique, rangés par site, province et région uniquement. */
export function placeParams(params) {
  const { search: _search, organisation: _organisation, node_type: _nodeType, ...place } = params;
  return place;
}

/** Libellé court du périmètre : « Guiriko › Houet › Bobo-Dioulasso ». */
export function scopeLabel({ region, province, site }) {
  return [region, province, site].filter(Boolean).join(" › ") || "Tout le réseau";
}

/** Libellé complet : localité, puis organisation et type s'ils sont choisis. */
export function fullScopeLabel({ region, province, site, organisation, nodeType }) {
  return [scopeLabel({ region, province, site }), organisation, nodeType]
    .filter(Boolean)
    .join(" · ");
}

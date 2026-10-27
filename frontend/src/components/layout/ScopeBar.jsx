import { MapPinned, RotateCcw } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { SearchField } from "../ui/Controls";
import { num } from "../../lib/format";
import { useGeoOptions } from "../../hooks/queries";
import { scopeLabel, useScopeStore } from "../../store/scope";

/**
 * Barre de périmètre — présente sur tous les tableaux de bord.
 *
 * Recherche libre + localité en cascade (région > province > site). Le
 * choix s'applique à TOUS les écrans à la fois (store/scope.js) : on ne
 * sélectionne pas « Guiriko » sur chaque page.
 *
 * Les listes sont construites sur le parc RÉEL (GET /geo/options) : une
 * province proposée contient toujours au moins un équipement, et son effectif
 * est affiché pour qu'on sache avant de cliquer ce que l'on va voir.
 */
function Select({ label, value, options, onChange, disabled, width }) {
  return (
    <select
      className="select"
      style={{ width, maxWidth: "100%" }}
      value={value ?? ""}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value || null)}
      aria-label={label}
      title={label}
    >
      <option value="">{disabled ? "—" : `${label} : toutes`}</option>
      {options.map((option) => (
        <option key={option.name} value={option.name}>
          {option.name} ({num(option.nodes)})
        </option>
      ))}
    </select>
  );
}

export default function ScopeBar() {
  const { region, province, site, search, setRegion, setProvince, setSite, setSearch, setPath, reset } =
    useScopeStore();
  const navigate = useNavigate();
  const location = useLocation();

  // Choix d'une suggestion : une localité devient le périmètre, un
  // équipement ou un incident ouvre sa fiche.
  const pick = (item) => {
    if (["region", "province", "site"].includes(item.kind)) {
      setPath(item.scope);
      return true;
    }
    if (item.kind === "node") {
      navigate(`/equipements/${encodeURIComponent(item.id)}`);
      return true;
    }
    if (item.kind === "incident") {
      navigate(`/incidents?id=${encodeURIComponent(item.id)}`);
      return true;
    }
    return false;
  };
  const options = useGeoOptions();

  const regions = options.data?.regions ?? [];
  const provinces = regions.find((item) => item.name === region)?.provinces ?? [];
  const sites = provinces.find((item) => item.name === province)?.sites ?? [];
  const filtered = Boolean(region || province || site || search);

  return (
    <div
      className="shrink-0 flex items-center gap-1.5 flex-wrap px-2.5 py-1.5 border-b"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      role="search"
      aria-label="Périmètre consulté"
    >
      <MapPinned size={14} style={{ color: "var(--accent-ink)" }} aria-hidden="true" />
      <SearchField
        value={search}
        onChange={setSearch}
        placeholder="Équipement, IP, site, incident…"
        width={230}
        suggest="global"
        onPick={pick}
      />
      <Select label="Région" value={region} options={regions} onChange={setRegion} width={170} />
      <Select
        label="Province"
        value={province}
        options={provinces}
        onChange={setProvince}
        disabled={!region}
        width={180}
      />
      <Select
        label="Site"
        value={site}
        options={sites}
        onChange={setSite}
        disabled={!province}
        width={200}
      />
      {filtered && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={reset} title="Tout le réseau">
          <RotateCcw size={12} /> Réinitialiser
        </button>
      )}
      {/* Rappel du périmètre et raccourci vers l'exploration territoriale —
          inutiles sur l'écran Territoire lui-même, qui affiche déjà les deux. */}
      {location.pathname !== "/territoire" && (
        <>
          <span
            className="ml-auto hidden lg:inline text-[11px] truncate"
            style={{ color: filtered ? "var(--accent-ink)" : "var(--ink-3)", maxWidth: 240 }}
            title="Périmètre appliqué à tous les tableaux de bord"
          >
            {scopeLabel({ region, province, site })}
            {search ? ` · « ${search} »` : ""}
          </span>
          <button type="button" className="btn btn-sm shrink-0" onClick={() => navigate("/territoire")}>
            Explorer ›
          </button>
        </>
      )}
    </div>
  );
}

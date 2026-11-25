import { CalendarRange, MapPinned, RotateCcw, SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { PeriodPicker } from "./TopBar";
import { SearchField, Segmented } from "../ui/Controls";
import { monthLabel, num } from "../../lib/format";
import { useGeoOptions } from "../../hooks/queries";
import { useScopeStore } from "../../store/scope";
import { MONTH_ROUTES, WINDOWS, usePeriodStore, useWindowStore } from "../../store/ui";
import { nodeTypeLabel } from "../../lib/vocabulary";

/**
 * Barre de périmètre — présente sur tous les tableaux de bord.
 *
 * Recherche libre + localité en cascade (région > province > site). Le
 * choix s'applique à TOUS les écrans à la fois (store/scope.js) : on ne
 * sélectionne pas « Guiriko » sur chaque page.
 *
 * Les listes sont construites sur le parc RÉEL (GET /geo/options) : une
 * province proposée contient toujours au moins un équipement, et son effectif
 * est affiché — avec son unité (« 113 équip. ») — pour qu'on sache avant de
 * cliquer ce que l'on va voir.
 *
 * BARRE UNIQUE (AM-30, INC-28) : localité, organisation, type et PÉRIODE.
 * Aucun écran n'a plus de filtre ni de période qui lui soit propre ; chaque
 * bloc affiche en pastille ce qui s'applique à lui (ui/ScopePill).
 */
function Select({ label, value, options, onChange, disabled, disabledHint, width, allLabel, format }) {
  // Libellé TOUJOURS visible (INC-33) : une liste qui n'affiche que « — »
  // ne dit pas ce qu'elle filtre tant qu'on n'a rien choisi au-dessus.
  return (
    <label className="flex items-center gap-1 text-[12px]" style={{ color: "var(--ink-3)" }}>
      <span>{label}</span>
      <select
        className="select"
        style={{ width, maxWidth: "100%" }}
        value={value ?? ""}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value || null)}
        aria-label={label}
        title={disabled ? disabledHint : label}
      >
        <option value="">{disabled ? disabledHint : allLabel}</option>
        {options.map((option) => (
          <option key={option.name} value={option.name}>
            {format ? format(option.name) : option.name} · {num(option.nodes)} équip.
          </option>
        ))}
      </select>
    </label>
  );
}

export default function ScopeBar() {
  const {
    region, province, site, organisation, nodeType, search,
    setRegion, setProvince, setSite, setOrganisation, setNodeType, setSearch, setPath, reset,
  } = useScopeStore();
  const hours = useWindowStore((s) => s.hours);
  const setHours = useWindowStore((s) => s.setHours);
  const { month, year, previousMonth, nextMonth, goToCurrent } = usePeriodStore();
  const liveMonth = usePeriodStore((s) => s.isCurrentPeriod());
  const navigate = useNavigate();
  const location = useLocation();
  const monthly = MONTH_ROUTES.includes(location.pathname);

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
  const filtered = Boolean(region || province || site || organisation || nodeType || search);
  const activeFilters = [region, province, site, organisation, nodeType].filter(Boolean).length;
  // Téléphone : la barre se replie sur la recherche et un bouton « Filtres » ;
  // déployée, elle occupait la moitié de l'écran. Au-delà, rien ne change
  // (`md:contents` rend l'enveloppe transparente).
  const [filtersOpen, setFiltersOpen] = useState(false);

  return (
    <div
      className="shrink-0 flex items-center gap-1.5 flex-wrap px-2.5 py-1.5 border-b"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      role="search"
      aria-label="Périmètre consulté"
    >
      <MapPinned size={14} className="hidden md:block" style={{ color: "var(--accent-ink)" }} aria-hidden="true" />
      <div className="flex-1 min-w-0 md:flex-none md:w-[250px]">
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Équipement, IP, site, ticket…  ( / )"
          width="100%"
          suggest="global"
          id="global-search"
          shortcut="/"
          onPick={pick}
        />
      </div>
      <span className="md:hidden">
        <button
          type="button"
          className="btn btn-sm"
          onClick={() => setFiltersOpen((open) => !open)}
          aria-expanded={filtersOpen}
          aria-controls="scope-filters"
        >
          <SlidersHorizontal size={13} />
          Filtres{activeFilters ? ` (${activeFilters})` : ""}
        </button>
      </span>
      <div
        id="scope-filters"
        className={`${filtersOpen ? "flex" : "hidden"} md:contents w-full flex-wrap items-center gap-1.5`}
      >
      <Select
        label="Région"
        value={region}
        options={regions}
        onChange={setRegion}
        allLabel="Toutes les régions"
        width={190}
      />
      <Select
        label="Province"
        value={province}
        options={provinces}
        onChange={setProvince}
        disabled={!region}
        disabledHint="Choisir d'abord une région"
        allLabel="Toutes les provinces"
        width={190}
      />
      <Select
        label="Site"
        value={site}
        options={sites}
        onChange={setSite}
        disabled={!province}
        disabledHint="Choisir d'abord une province"
        allLabel="Tous les sites"
        width={200}
      />
      {(options.data?.organisations?.length ?? 0) > 0 && (
        <Select
          label="Organisation"
          value={organisation}
          options={options.data.organisations}
          onChange={setOrganisation}
          allLabel="Toutes"
          width={170}
        />
      )}
      {(options.data?.node_types?.length ?? 0) > 0 && (
        <Select
          label="Type"
          value={nodeType}
          options={options.data.node_types}
          onChange={setNodeType}
          format={nodeTypeLabel}
          allLabel="Tous les types"
          width={150}
        />
      )}
      {/* Mois : le mois en cours montre le direct, un mois passé ses seules
          données (MonthView). */}
      {monthly && (
        <PeriodPicker
          label={monthLabel(month, year)}
          onPrevious={previousMonth}
          onNext={nextMonth}
          onCurrent={goToCurrent}
          isCurrent={liveMonth}
        />
      )}
      {(liveMonth || !monthly) && (
      <span className="flex items-center gap-1 text-[12px]" style={{ color: "var(--ink-3)" }}>
        <CalendarRange size={13} aria-hidden="true" />
        <span>Période</span>
        <Segmented ariaLabel="Période d'observation" value={hours} onChange={setHours} options={WINDOWS} />
      </span>
      )}
      {filtered && (
        <button type="button" className="btn btn-ghost btn-sm" onClick={reset} title="Tout le réseau">
          <RotateCcw size={12} /> Réinitialiser
        </button>
      )}
      </div>
      {/* Rappel du périmètre et raccourci vers l'exploration territoriale —
          inutiles sur l'écran Territoire lui-même, qui affiche déjà les deux. */}
      {location.pathname !== "/territoire" && (
        <>
          {/* AM-16 : fil d'Ariane cliquable — remonter d'un niveau en un clic. */}
          <nav
            className="ml-auto hidden lg:flex items-center gap-0.5 text-[12px] min-w-0"
            aria-label="Périmètre appliqué à tous les tableaux de bord"
            title="Périmètre appliqué à tous les tableaux de bord"
          >
            {[
              { label: "Tout le réseau", path: {} },
              region && { label: region, path: { region } },
              province && { label: province, path: { region, province } },
              site && { label: site, path: { region, province, site } },
            ]
              .filter(Boolean)
              .map((crumb, index, all) => (
                <span key={crumb.label} className="flex items-center gap-0.5 min-w-0">
                  {index > 0 && <span style={{ color: "var(--ink-3)" }}>›</span>}
                  {index === all.length - 1 ? (
                    <span className="truncate font-semibold" style={{ color: "var(--accent-ink)", maxWidth: 160 }}>
                      {crumb.label}
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="truncate hover:underline"
                      style={{ color: "var(--ink-2)", maxWidth: 140 }}
                      onClick={() => setPath(crumb.path)}
                    >
                      {crumb.label}
                    </button>
                  )}
                </span>
              ))}
            {(organisation || nodeType || search) && (
              <span className="truncate" style={{ color: "var(--accent-ink)", maxWidth: 200 }}>
                {[organisation, nodeType && nodeTypeLabel(nodeType), search && `« ${search} »`]
                  .filter(Boolean)
                  .map((part) => ` · ${part}`)
                  .join("")}
              </span>
            )}
          </nav>
          <span className="hidden sm:inline-flex shrink-0">
            <button type="button" className="btn btn-sm" onClick={() => navigate("/territoire")}>
              Explorer ›
            </button>
          </span>
        </>
      )}
    </div>
  );
}

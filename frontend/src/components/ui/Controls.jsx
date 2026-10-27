import { Search, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useSuggestions } from "../../hooks/queries";

/** Barre d'outils d'un écran : filtres à gauche, actions à droite. */
export function Toolbar({ children, right }) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {children}
      {right && <div className="ml-auto flex items-center gap-2">{right}</div>}
    </div>
  );
}

/** Contrôle segmenté — fenêtre temporelle, mode d'affichage, filtre d'état. */
export function Segmented({ options, value, onChange, ariaLabel }) {
  return (
    <div className="seg" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
          title={option.hint}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/**
 * Champ de recherche avec anti-rebond.
 *
 * 300 ms : au-delà la frappe paraît molle, en deçà on émet une requête
 * par caractère — sur un inventaire de plusieurs milliers d'équipements,
 * chacune balaie la table entière.
 */
const SUGGESTION_KIND = {
  region: "Région",
  province: "Province",
  site: "Site",
  node: "Équipement",
  incident: "Incident iTop",
  alert: "Alerte",
  maintenance: "Maintenance",
  intervention: "Intervention",
};

/**
 * Suggestions sous le champ, pendant la frappe (à partir de 2 caractères).
 *
 * `suggest` : préréglage (voir hooks/queries.js::SUGGEST_KINDS) ou liste de
 * types. `onPick(suggestion)` : rendre `true` si le choix a été traité (aller
 * sur une fiche, appliquer une localité) ; sinon le libellé remplit le champ
 * et la recherche s'applique tout de suite.
 */
function useSuggestBox({ draft, suggest, onPick, apply }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [term, setTerm] = useState(draft);
  useEffect(() => {
    const timer = setTimeout(() => setTerm(draft), 150);
    return () => clearTimeout(timer);
  }, [draft]);
  const query = useSuggestions(open ? term : "", suggest);
  const items = (open && term.trim().length >= 2 ? query.data : null) ?? [];

  const pick = (item) => {
    setOpen(false);
    setActive(-1);
    if (onPick?.(item)) {
      apply("");
      return;
    }
    apply(item.value ?? item.label);
  };

  const onKeyDown = (event) => {
    if (!items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => (index + 1) % items.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index <= 0 ? items.length - 1 : index - 1));
    } else if (event.key === "Enter" && active >= 0) {
      event.preventDefault();
      pick(items[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };
  return { open, setOpen, active, setActive, items, pick, onKeyDown, loading: query.isFetching };
}

export function SearchField({
  value,
  onChange,
  placeholder = "Rechercher…",
  width = 200,
  delay = 300,
  suggest,
  onPick,
}) {
  const [draft, setDraft] = useState(value ?? "");
  const boxRef = useRef(null);

  // Resynchronise quand la valeur est réinitialisée depuis l'extérieur
  // (bouton « effacer les filtres »).
  useEffect(() => setDraft(value ?? ""), [value]);

  useEffect(() => {
    if (draft === (value ?? "")) return undefined;
    const timer = setTimeout(() => onChange(draft), delay);
    return () => clearTimeout(timer);
  }, [draft, delay, onChange, value]);

  const apply = (text) => {
    setDraft(text);
    onChange(text);
  };
  const box = useSuggestBox({ draft, suggest, onPick, apply });

  // Fermeture au clic en dehors.
  useEffect(() => {
    if (!box.open) return undefined;
    const onDown = (event) => {
      if (boxRef.current && !boxRef.current.contains(event.target)) box.setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [box]);

  const showList = suggest && box.open && draft.trim().length >= 2;

  return (
    <div className="relative" style={{ width }} ref={boxRef}>
      <Search
        size={13}
        className="absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none"
        style={{ color: "var(--ink-3)" }}
      />
      <input
        className="input"
        style={{ paddingLeft: 24, paddingRight: draft ? 24 : 8 }}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => {
          setDraft(event.target.value);
          box.setOpen(true);
          box.setActive(-1);
        }}
        onFocus={() => box.setOpen(true)}
        onKeyDown={box.onKeyDown}
        role={suggest ? "combobox" : undefined}
        aria-expanded={suggest ? Boolean(showList && box.items.length) : undefined}
        aria-autocomplete={suggest ? "list" : undefined}
      />
      {draft && (
        <button
          type="button"
          className="absolute right-1.5 top-1/2 -translate-y-1/2"
          style={{ color: "var(--ink-3)" }}
          onClick={() => apply("")}
          aria-label="Effacer la recherche"
        >
          <X size={12} />
        </button>
      )}
      {showList && (box.items.length > 0 || !box.loading) && (
        <ul
          role="listbox"
          className="absolute left-0 top-full mt-1 z-[1500] panel py-1 overflow-auto"
          style={{ minWidth: Math.max(width, 340), maxHeight: 340, boxShadow: "0 12px 32px rgba(0,0,0,.35)" }}
        >
          {box.items.length === 0 ? (
            <li className="px-2.5 py-1.5 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              Aucune suggestion — Entrée pour rechercher « {draft.trim()} »
            </li>
          ) : (
            box.items.map((item, index) => (
              <li
                key={`${item.kind}-${item.id ?? item.label}`}
                role="option"
                aria-selected={index === box.active}
                className="px-2.5 py-1.5 cursor-pointer flex items-baseline gap-2"
                style={{ background: index === box.active ? "var(--surface-2)" : undefined }}
                onMouseEnter={() => box.setActive(index)}
                onMouseDown={(event) => {
                  event.preventDefault();
                  box.pick(item);
                }}
              >
                <span
                  className="text-[9.5px] uppercase tracking-[0.06em] shrink-0"
                  style={{ color: "var(--accent-ink)", width: 78 }}
                >
                  {SUGGESTION_KIND[item.kind] ?? item.kind}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[12px] truncate">{item.label}</span>
                  {item.detail && (
                    <span className="block text-[10.5px] truncate" style={{ color: "var(--ink-3)" }}>
                      {item.detail}
                    </span>
                  )}
                </span>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}

/** Liste déroulante de filtre — « Tous » est toujours la première option. */
export function FilterSelect({ label, value, onChange, options, allLabel = "Tous", width = 150 }) {
  return (
    <select
      className="select"
      style={{ width }}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value || null)}
      aria-label={label}
      title={label}
    >
      <option value="">{allLabel}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/** Champ de formulaire : libellé, aide, message d'erreur. */
export function Field({ label, hint, error, required, children, className = "" }) {
  return (
    <label className={`block ${className}`}>
      <span className="field-label">
        {label}
        {required && <span style={{ color: "var(--sev-critical)" }}> *</span>}
      </span>
      {children}
      {hint && !error && (
        <span className="block text-[10.5px] mt-1" style={{ color: "var(--ink-3)" }}>
          {hint}
        </span>
      )}
      {error && (
        <span className="block text-[10.5px] mt-1" style={{ color: "var(--sev-critical)" }}>
          {error}
        </span>
      )}
    </label>
  );
}

/** Bandeau de message inline (succès / erreur / information). */
export function Notice({ tone = "info", children, onClose }) {
  const color = {
    info: "var(--accent-ink)",
    success: "var(--state-up)",
    warning: "var(--sev-medium)",
    error: "var(--sev-critical)",
  }[tone];

  return (
    <div
      className="flex items-start gap-2 px-2.5 py-1.5 text-[12px] rounded-[3px] border"
      style={{
        color,
        background: `color-mix(in srgb, ${color} 10%, transparent)`,
        borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
      }}
      role={tone === "error" ? "alert" : "status"}
    >
      <span className="min-w-0 flex-1">{children}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Fermer" style={{ color }}>
          <X size={12} />
        </button>
      )}
    </div>
  );
}

/** Onglets internes à un écran. */
export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="flex items-center gap-0.5 border-b" style={{ borderColor: "var(--border)" }}>
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            className="px-2.5 h-[28px] text-[12px] font-medium border-b-2 -mb-px transition-colors"
            style={{
              color: active ? "var(--ink)" : "var(--ink-3)",
              borderColor: active ? "var(--accent)" : "transparent",
            }}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="num ml-1.5 text-[11px]" style={{ color: "var(--ink-3)" }}>
                {tab.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

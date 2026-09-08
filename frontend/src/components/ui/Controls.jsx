import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";

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
export function SearchField({ value, onChange, placeholder = "Rechercher…", width = 200, delay = 300 }) {
  const [draft, setDraft] = useState(value ?? "");

  // Resynchronise quand la valeur est réinitialisée depuis l'extérieur
  // (bouton « effacer les filtres »).
  useEffect(() => setDraft(value ?? ""), [value]);

  useEffect(() => {
    if (draft === (value ?? "")) return undefined;
    const timer = setTimeout(() => onChange(draft), delay);
    return () => clearTimeout(timer);
  }, [draft, delay, onChange, value]);

  return (
    <div className="relative" style={{ width }}>
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
        onChange={(event) => setDraft(event.target.value)}
      />
      {draft && (
        <button
          type="button"
          className="absolute right-1.5 top-1/2 -translate-y-1/2"
          style={{ color: "var(--ink-3)" }}
          onClick={() => setDraft("")}
          aria-label="Effacer la recherche"
        >
          <X size={12} />
        </button>
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

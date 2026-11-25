/**
 * Mise en forme des valeurs affichées.
 *
 * Deux principes, tenus partout :
 *
 * 1. Une donnée absente s'écrit « — », jamais « 0 », « N/A » ni une case
 *    vide. Sur un écran d'exploitation, un zéro affiché à la place d'une
 *    mesure manquante se lit comme « tout va bien » alors qu'il signifie
 *    « on ne sait pas » — c'est la confusion la plus coûteuse possible.
 * 2. Les durées se lisent dans l'unité de la conversation d'astreinte :
 *    « 4 min », « 2 h 15 », « 3 j » — jamais « 135.0 minutes ».
 */

const NBSP = " "; // espace fine insécable, séparateur de milliers FR

export const DASH = "—";

export const isNil = (value) => value === null || value === undefined || Number.isNaN(value);

/** Entier avec séparateur de milliers. */
export function num(value, fallback = DASH) {
  if (isNil(value)) return fallback;
  return Math.round(Number(value))
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

/**
 * « 1 site touché », « 3 sites touchés » — plus de « (s) » (INC-17).
 * `plural` par défaut : le singulier suivi d'un « s » sur chaque mot.
 */
export function plural(count, singular, pluralForm) {
  const many = Number(count) > 1;
  const word = many
    ? pluralForm ?? singular.split(" ").map((part) => `${part}s`).join(" ")
    : singular;
  return `${num(count)} ${word}`;
}

/** Téléphone : mêmes règles que le backend (schemas/users.py). Vide accepté. */
export function phoneValid(value) {
  const text = (value ?? "").trim();
  if (!text) return true;
  const digits = text.replace(/\D/g, "").length;
  return /^\+?[0-9][0-9 ().-]*$/.test(text) && digits >= 8 && digits <= 15;
}

/** Décimal à `digits` chiffres après la virgule. */
export function decimal(value, digits = 1, fallback = DASH) {
  if (isNil(value)) return fallback;
  return Number(value).toFixed(digits).replace(".", ",");
}

/**
 * Disponibilité. Sans valeur, le backend dit qu'AUCUN équipement du
 * périmètre n'est supervisé (AM-29, INC-40) : on l'écrit en toutes lettres,
 * jamais « 0 % » ni « — », qui se liraient « tout est en panne » ou
 * « défaut d'affichage ».
 */
export const UNSUPERVISED = "Non supervisé";

export function availabilityPct(value, digits = 1) {
  return pct(value, digits, UNSUPERVISED);
}

/**
 * Base d'un indicateur de disponibilité instantané (AM-34, INC-42) :
 * « 956 / 1 381 supervisés · 12 non supervisés · instantané, 10:42 ».
 */
export function availabilityBasis(basis) {
  if (!basis) return undefined;
  const parts = [`${num(basis.up)} / ${num(basis.supervised)} supervisés en service`];
  if (basis.unsupervised) parts.push(`${num(basis.unsupervised)} non supervisé(s), à part`);
  if (basis.maintenance) parts.push(`${num(basis.maintenance)} en maintenance`);
  const at = basis.computed_at ? new Date(basis.computed_at) : null;
  parts.push(
    at && !Number.isNaN(at.getTime())
      ? `instantané, calculé à ${at.toLocaleTimeString("fr-FR", { timeZone: NOC_TIMEZONE, hour: "2-digit", minute: "2-digit" })}`
      : "instantané",
  );
  return parts.join(" · ");
}

/** Pourcentage. `digits` à 2 pour la disponibilité (99,95 % ≠ 100 %). */
export function pct(value, digits = 1, fallback = DASH) {
  if (isNil(value)) return fallback;
  return `${decimal(value, digits)}${NBSP}%`;
}

/**
 * Durée en minutes → forme courte.
 * 47 → « 47 min » · 135 → « 2 h 15 » · 4320 → « 3 j »
 */
export function duration(minutes, fallback = DASH) {
  if (isNil(minutes)) return fallback;
  const total = Math.max(0, Math.round(Number(minutes)));
  if (total < 1) return "< 1 min";
  if (total < 60) return `${total}${NBSP}min`;
  if (total < 60 * 24) {
    const hours = Math.floor(total / 60);
    const rest = total % 60;
    return rest === 0 ? `${hours}${NBSP}h` : `${hours}${NBSP}h${NBSP}${String(rest).padStart(2, "0")}`;
  }
  const days = Math.floor(total / 1440);
  const hours = Math.floor((total % 1440) / 60);
  return hours === 0 ? `${days}${NBSP}j` : `${days}${NBSP}j${NBSP}${hours}${NBSP}h`;
}

/** Ancienneté depuis un horodatage ISO. */
export function ageFrom(isoDate, fallback = DASH) {
  if (!isoDate) return fallback;
  const ms = Date.now() - new Date(isoDate).getTime();
  if (Number.isNaN(ms)) return fallback;
  return duration(ms / 60000, fallback);
}

/**
 * Fuseau du NOC (INC-14, AM-28) : toutes les heures sont affichées en heure
 * du Burkina Faso (GMT, sans heure d'été), quel que soit le réglage du poste,
 * et les dates en jj/mm/aaaa HH:mm (année sur 4 chiffres).
 */
export const NOC_TIMEZONE = "Africa/Ouagadougou";

const dateTimeFmt = new Intl.DateTimeFormat("fr-FR", {
  timeZone: NOC_TIMEZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

const timeFmt = new Intl.DateTimeFormat("fr-FR", {
  timeZone: NOC_TIMEZONE,
  hour: "2-digit",
  minute: "2-digit",
});

const dateFmt = new Intl.DateTimeFormat("fr-FR", {
  timeZone: NOC_TIMEZONE,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const dayMonthFmt = new Intl.DateTimeFormat("fr-FR", {
  timeZone: NOC_TIMEZONE,
  day: "2-digit",
  month: "short",
});

export function dateTime(iso, fallback = DASH) {
  if (!iso) return fallback;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? fallback : dateTimeFmt.format(d);
}

export function time(iso, fallback = DASH) {
  if (!iso) return fallback;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? fallback : timeFmt.format(d);
}

export function date(iso, fallback = DASH) {
  if (!iso) return fallback;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? fallback : dateFmt.format(d);
}

export function dayMonth(iso, fallback = DASH) {
  if (!iso) return fallback;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? fallback : dayMonthFmt.format(d);
}

/**
 * Horodatage adapté à la distance dans le temps : l'heure seule pour
 * aujourd'hui, la date complète au-delà. Un opérateur qui regarde le
 * mur d'alertes veut « 14:32 », pas « 07/09/26 14:32 » répété 40 fois.
 */
export function smartTime(iso, fallback = DASH) {
  if (!iso) return fallback;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return fallback;
  const now = new Date();
  const sameDay =
    d.getDate() === now.getDate() &&
    d.getMonth() === now.getMonth() &&
    d.getFullYear() === now.getFullYear();
  return sameDay ? timeFmt.format(d) : dateTimeFmt.format(d);
}

/** Débit : passe automatiquement en Gb/s au-delà de 1000 Mb/s. */
export function bandwidth(mbps, fallback = DASH) {
  if (isNil(mbps)) return fallback;
  const value = Number(mbps);
  if (value >= 1000) return `${decimal(value / 1000, 2)}${NBSP}Gb/s`;
  return `${decimal(value, value < 10 ? 1 : 0)}${NBSP}Mb/s`;
}

/** Signe explicite — un delta sans signe ne veut rien dire. */
export function delta(value, formatter = num, fallback = DASH) {
  if (isNil(value)) return fallback;
  const sign = Number(value) > 0 ? "+" : Number(value) < 0 ? "−" : "±";
  return `${sign}${formatter(Math.abs(Number(value)))}`;
}

export const MONTHS_FR = [
  "janvier", "février", "mars", "avril", "mai", "juin",
  "juillet", "août", "septembre", "octobre", "novembre", "décembre",
];

export const MONTHS_FR_SHORT = [
  "janv", "févr", "mars", "avr", "mai", "juin",
  "juil", "août", "sept", "oct", "nov", "déc",
];

export function monthLabel(month, year) {
  return `${MONTHS_FR[month - 1] ?? ""} ${year}`;
}

/** Texte tronqué proprement, pour les descriptions d'incident en tableau. */
export function ellipsis(text, max = 90) {
  if (!text) return DASH;
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

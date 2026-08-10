// Shared display formatters.

const MIN_PER_HOUR = 60;
const MIN_PER_DAY = 1440;
const MIN_PER_MONTH = MIN_PER_DAY * 30;
const MIN_PER_YEAR = MIN_PER_DAY * 365;

/**
 * Relative age of an incident, from an age in minutes.
 *
 * Goes all the way up to years on purpose. The demo seed only ever produced
 * incidents inside a six-month window, so stopping at days was fine; the real
 * NetXMS alarm set contains problems that have been open since 2024, and
 * "il y a 775j" is a number the reader has to do arithmetic on before it means
 * anything.
 */
export const formatAge = (minutes) => {
  if (minutes == null) return "—";
  if (minutes < MIN_PER_HOUR) return `il y a ${minutes} min`;
  if (minutes < MIN_PER_DAY) return `il y a ${Math.round(minutes / MIN_PER_HOUR)}h`;
  if (minutes < MIN_PER_MONTH) return `il y a ${Math.round(minutes / MIN_PER_DAY)}j`;
  if (minutes < MIN_PER_YEAR) return `il y a ${Math.round(minutes / MIN_PER_MONTH)} mois`;
  const years = minutes / MIN_PER_YEAR;
  // One decimal below 10 years: "il y a 2,1 ans" still distinguishes an alarm
  // left open since last year from one left open since 2022.
  const value = years < 10 ? years.toFixed(1).replace(".", ",") : Math.round(years);
  return `il y a ${value} ans`;
};

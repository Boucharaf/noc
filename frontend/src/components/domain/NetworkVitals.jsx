import Stat from "../ui/Stat";
import { bandwidth, decimal, num, pct } from "../../lib/format";
import { metricMeta, thresholdColor } from "../../lib/vocabulary";

/**
 * Constantes vitales du réseau.
 *
 * Les six mesures que le document métier appelle « KPI réseau » :
 * disponibilité, pertes, latence, bande passante, CPU, mémoire — plus le
 * nombre d'équipements qui remontent effectivement des données.
 *
 * Ce DERNIER chiffre est le plus important de la rangée, et c'est celui
 * qu'aucun dashboard générique n'affiche : une latence moyenne de 12 ms
 * calculée sur 4 équipements au lieu de 300 n'est pas une bonne
 * nouvelle, c'est une panne de collecte. La tuile passe donc en alerte
 * quand la couverture s'effondre, au lieu d'afficher fièrement une
 * moyenne flatteuse.
 */
export default function NetworkVitals({ data, expectedNodes, compact = false }) {
  // Ce que l'ETL publie RÉELLEMENT : une métrique absente de cette liste
  // n'est pas à zéro, elle n'est pas collectée. La distinction est faite
  // ici une fois pour toutes.
  const available = data?.metric_types_available ?? [];
  const has = (type) => available.includes(type);

  const reporting = data?.nodes_reporting ?? 0;
  const coverageRatio = expectedNodes ? reporting / expectedNodes : null;
  const reportingColor =
    coverageRatio === null
      ? undefined
      : coverageRatio >= 0.9
        ? "var(--state-up)"
        : coverageRatio >= 0.6
          ? "var(--sev-medium)"
          : "var(--sev-critical)";

  const tiles = [
    {
      key: "availability_pct",
      label: "Disponibilité",
      value: has("availability_pct") ? pct(data?.availability_pct, 2) : null,
      color: thresholdColor("availability_pct", data?.availability_pct),
      target: "≥ 99 %",
    },
    {
      key: "packet_loss_pct",
      label: "Perte paquets",
      value: has("packet_loss_pct") ? pct(data?.packet_loss_pct, 2) : null,
      color: thresholdColor("packet_loss_pct", data?.packet_loss_pct),
      target: "≤ 2 %",
    },
    {
      key: "latency_ms",
      label: "Latence moy.",
      value: has("latency_ms") ? `${decimal(data?.avg_latency_ms, 0)} ms` : null,
      color: thresholdColor("latency_ms", data?.avg_latency_ms),
      target: "≤ 100 ms",
    },
    {
      key: "bandwidth_in_mbps",
      label: "Trafic entrant",
      value: has("bandwidth_in_mbps") ? bandwidth(data?.avg_bandwidth_in_mbps) : null,
      color: undefined,
      target: null,
    },
    {
      key: "cpu_pct",
      label: "CPU moyen",
      value: has("cpu_pct") ? pct(data?.avg_cpu_pct, 0) : null,
      color: thresholdColor("cpu_pct", data?.avg_cpu_pct),
      target: "≤ 80 %",
    },
    {
      key: "ram_pct",
      label: "Mémoire moy.",
      value: has("ram_pct") ? pct(data?.avg_ram_pct, 0) : null,
      color: thresholdColor("ram_pct", data?.avg_ram_pct),
      target: "≤ 85 %",
    },
  ];

  return (
    <>
      {tiles.map((tile) => (
        <Stat
          key={tile.key}
          label={tile.label}
          value={tile.value ?? "—"}
          color={tile.value ? tile.color : "var(--ink-3)"}
          target={tile.value ? tile.target : undefined}
          // Sans métrique disponible, on dit POURQUOI la case est vide.
          // « — » seul laisse croire à un bug de l'interface alors que
          // c'est un connecteur qui ne publie pas cette mesure.
          hint={tile.value ? undefined : `non collectée (${metricMeta(tile.key).label})`}
          compact={compact}
        />
      ))}
      <Stat
        label="Équip. qui remontent"
        value={num(reporting)}
        color={reportingColor}
        compact={compact}
        hint={
          expectedNodes
            ? `sur ${num(expectedNodes)} actifs`
            : "aucune référence de parc"
        }
        status={
          coverageRatio !== null && coverageRatio < 0.6 ? "var(--sev-critical)" : undefined
        }
      />
      <Stat
        label="Équipements HS"
        value={num(data?.nodes_down, "0")}
        color={data?.nodes_down ? "var(--state-down)" : "var(--state-up)"}
        compact={compact}
        hint={`fenêtre ${data?.window_hours ?? 24} h`}
      />
    </>
  );
}

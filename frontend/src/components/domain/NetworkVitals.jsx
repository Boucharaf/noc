import Stat from "../ui/Stat";
import { bandwidth, decimal, num, pct } from "../../lib/format";
import { thresholdColor } from "../../lib/vocabulary";
import { useLiveTrend } from "../../hooks/queries";

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
// Jauge « objectif » de chaque mesure : la cible est un repère sur la
// barre, l'écart se voit sans lire. Pour une mesure où plus bas est mieux
// (latence, pertes), la jauge se remplit vers le seuil à NE PAS dépasser.
const GAUGES = {
  availability_pct: { target: 99, max: 100 },
  packet_loss_pct: { target: 2, max: 10 },
  latency_ms: { target: 100, max: 400 },
  cpu_pct: { target: 80, max: 100 },
  ram_pct: { target: 85, max: 100 },
  disk_pct: { target: 90, max: 100 },
};

const HELP = {
  availability_pct:
    "Part des équipements suivis qui répondent, hors maintenance planifiée. Un équipement à l'état inconnu compte comme non disponible.",
  packet_loss_pct: "Pertes de paquets moyennes au ping, sur les équipements mesurés par Zabbix ou Centreon.",
  latency_ms: "Temps de réponse moyen au ping (aller-retour), sur les équipements mesurés.",
  bandwidth_in_mbps: "Débit up moyen par équipement mesuré (somme de ses interfaces).",
  bandwidth_out_mbps: "Débit down moyen par équipement mesuré (somme de ses interfaces).",
  cpu_pct: "Charge processeur moyenne des équipements mesurés.",
  ram_pct: "Occupation mémoire moyenne des équipements mesurés.",
  disk_pct: "Occupation disque moyenne des équipements mesurés.",
  uptime: "Temps moyen depuis le dernier redémarrage.",
};

export default function NetworkVitals({ data, expectedNodes, compact = false }) {
  const trend = useLiveTrend();
  // Ce que l'ETL publie RÉELLEMENT : une métrique absente de cette liste
  // n'est pas à zéro, elle n'est pas collectée. La distinction est faite
  // ici une fois pour toutes.
  const available = data?.metric_types_available ?? [];
  const has = (type) => available.includes(type);

  const reporting = data?.nodes_reporting ?? null;
  const coverageRatio = expectedNodes && reporting !== null ? reporting / expectedNodes : null;
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
      label: "Débit up",
      value: has("bandwidth_in_mbps") ? bandwidth(data?.avg_bandwidth_in_mbps) : null,
      color: undefined,
      target: null,
    },
    {
      key: "bandwidth_out_mbps",
      label: "Débit down",
      value: has("bandwidth_out_mbps") ? bandwidth(data?.avg_bandwidth_out_mbps) : null,
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
    {
      key: "disk_pct",
      label: "Disque moyen",
      value: has("disk_pct") ? pct(data?.avg_disk_pct, 0) : null,
      color: thresholdColor("disk_pct", data?.avg_disk_pct),
      target: "≤ 90 %",
    },
    {
      key: "uptime",
      label: "Uptime moyen",
      value: has("uptime") ? `${decimal(data?.avg_uptime, 1)} j` : null,
      color: thresholdColor("uptime", data?.avg_uptime),
      target: null,
    },
  ];

  // Seules les mesures COLLECTÉES ont une tuile ; les autres sont nommées dans
  // une tuile unique. Sept cases « — » côte à côte occupaient une rangée
  // entière de l'écran pour dire une seule chose : « non collecté ».
  const collected = tiles.filter((tile) => tile.value);
  const missing = tiles.filter((tile) => !tile.value);

  return (
    <>
      {collected.map((tile) => (
        <Stat
          key={tile.key}
          label={tile.label}
          value={tile.value}
          color={tile.color}
          target={tile.target}
          compact={compact}
          help={HELP[tile.key]}
          gauge={
            GAUGES[tile.key] && {
              ...GAUGES[tile.key],
              value:
                tile.key === "availability_pct"
                  ? data?.availability_pct
                  : tile.key === "latency_ms"
                    ? data?.avg_latency_ms
                    : tile.key === "packet_loss_pct"
                      ? data?.packet_loss_pct
                      : data?.[`avg_${tile.key}`],
            }
          }

          // Une moyenne sur 6 équipements d'un parc de 1 300 doit le dire.
          hint={
            data?.metric_nodes?.[tile.key] != null
              ? `sur ${num(data.metric_nodes[tile.key])} équip. mesuré(s)`
              : undefined
          }
        />
      ))}
      {missing.length > 0 && (
        <Stat
          label="Mesures non collectées"
          value={num(missing.length)}
          color="var(--ink-3)"
          compact={compact}
          // On dit lesquelles et pourquoi : sans cela la case vide passe pour
          // un défaut d'affichage alors qu'aucun connecteur ne la publie.
          hint={missing.map((tile) => tile.label.toLowerCase()).join(", ")}
        />
      )}
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
        value={num(data?.nodes_down)}
        color={data?.nodes_down ? "var(--state-down)" : "var(--state-up)"}
        compact={compact}
        hint="évolution sur 24 h"
        spark={trend.data?.nodesDown}
        invertDelta
      />
    </>
  );
}

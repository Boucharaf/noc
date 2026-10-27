import { Link } from "react-router-dom";
import { Wrench } from "lucide-react";

import DataTable from "../ui/Table";
import { SeverityBadge, ToolTag } from "../ui/Badge";
import { ageFrom, dateTime, duration, ellipsis, smartTime } from "../../lib/format";

/**
 * Tableau d'incidents — le composant le plus regardé de l'application.
 *
 * Choix de colonnes, dans l'ordre où un opérateur lit une ligne :
 *   gravité → âge → équipement → site → cause → description → statut.
 * L'ÂGE arrive avant tout le reste parce que c'est la question posée en
 * salle (« ça dure depuis combien de temps ? ») ; l'horodatage absolu est
 * relégué en infobulle, il ne sert qu'au rapport a posteriori.
 *
 * `variant` adapte la densité au contexte : "wall" pour le mur d'alertes
 * (peu de colonnes, lisible de loin), "full" pour l'écran d'analyse.
 */
export default function IncidentTable({
  incidents,
  onSelect,
  selectedId,
  variant = "full",
  emptyRow,
}) {
  const compact = variant === "wall";

  const columns = [
    {
      key: "severity",
      header: "Gravité",
      width: 118,
      render: (row) => (
        <SeverityBadge severity={row.severity} short={compact} source={row.source_severity} tool={row.tool ?? row.source_tool} />
      ),
    },
    {
      key: "age",
      header: "Âge",
      width: 66,
      align: "right",
      mono: true,
      render: (row) => (
        <span
          title={`Détecté le ${dateTime(row.detected_at)}`}
          style={{
            // Au-delà de 4 h sans résolution, l'âge devient l'information
            // principale de la ligne : il est coloré pour ressortir dans
            // le balayage vertical de la colonne.
            color:
              row.status !== "resolved" && row.status !== "closed" && (row.age_minutes ?? 0) > 240
                ? "var(--sev-medium)"
                : "var(--ink-2)",
          }}
        >
          {row.age_minutes !== null && row.age_minutes !== undefined
            ? duration(row.age_minutes)
            : ageFrom(row.detected_at)}
        </span>
      ),
    },
    {
      key: "node",
      header: "Équipement",
      width: compact ? 150 : 190,
      render: (row) =>
        row.node_id ? (
          <Link
            to={`/equipements/${row.node_id}`}
            className="hover:underline"
            style={{ color: "var(--ink)", textDecoration: "none" }}
            onClick={(event) => event.stopPropagation()}
            title="Ouvrir la fiche équipement"
          >
            {row.node_name}
          </Link>
        ) : (
          <span style={{ color: "var(--ink-3)" }}>{row.node_name || "—"}</span>
        ),
    },
    {
      key: "locality",
      header: "Site",
      width: 130,
      render: (row) => (
        <span style={{ color: "var(--ink-2)" }} title={row.region ? `Région : ${row.region}` : undefined}>
          {row.locality || "—"}
        </span>
      ),
    },
  ];

  columns.push({
    key: "description",
    header: "Description",
    // Retour à la ligne autorisé : en `truncate-cell` sans largeur fixe, la
    // colonne était écrasée à zéro et le message de l'outil — la donnée
    // technique principale — ne s'affichait plus du tout.
    wrap: true,
    render: (row) => (
      <span className="flex items-start gap-1.5" style={{ minWidth: 220 }} title={row.description ?? ""}>
        {row.is_maintenance && (
          <Wrench
            size={11}
            style={{ color: "var(--state-maintenance)" }}
            aria-label="Pendant une fenêtre de maintenance planifiée"
          />
        )}
        <span style={{ color: "var(--ink-2)" }}>
          {ellipsis(row.description, compact ? 60 : 110)}
        </span>
      </span>
    ),
  });

  // Caractéristiques TECHNIQUES seulement : plus de cause, de statut de
  // traitement ni d'affectation — ce circuit vit dans iTop. Reste l'état
  // d'acquittement tel que l'OUTIL source le déclare.
  columns.push({
    key: "ack",
    header: "Acquit. outil",
    width: 96,
    render: (row) =>
      row.acknowledged ? (
        <span style={{ color: "var(--accent-ink)" }}>acquittée</span>
      ) : (
        <span style={{ color: "var(--ink-3)" }}>—</span>
      ),
  });

  if (!compact) {
    columns.push({
      key: "detected",
      header: "Détecté",
      width: 104,
      mono: true,
      render: (row) => (
        <span style={{ color: "var(--ink-3)" }} title={dateTime(row.detected_at)}>
          {smartTime(row.detected_at)}
        </span>
      ),
    });
    columns.push({
      key: "tool",
      header: "Source",
      width: 84,
      render: (row) => (
        <div className="flex flex-col items-start gap-0.5">
          <ToolTag tool={row.source_tool} />
          <span
            className="text-[10px]"
            style={{ color: row.stale ? "var(--sev-medium)" : "var(--ink-3)" }}
          >
            {row.stale
              ? `Périmé · ${row.kind === "itsm_ticket" ? "ITSM" : "supervision"}`
              : row.kind === "itsm_ticket"
                ? "Ticket ITSM"
                : row.kind === "manual_incident"
                  ? "Incident signalé"
                  : "Alerte technique"}
          </span>
        </div>
      ),
    });
  }

  if (!incidents?.length && emptyRow) return emptyRow;

  return (
    <DataTable
      columns={columns}
      rows={incidents ?? []}
      rowKey={(row) => row.id}
      onRowClick={onSelect}
      selectedKey={selectedId}
      // Liseré de gravité en tête de ligne : lisible à trois mètres, là
      // où le mot « critique » ne l'est pas. Volontairement PAS de
      // clignotement au niveau de la ligne — sur une file de 40 entrées
      // il en resterait la moitié à clignoter, et l'œil cesserait de les
      // voir. Le clignotement est réservé aux compteurs du bandeau
      // d'état et du mur d'écrans, où il porte encore une information.
      rowClassName={(row) => `sev-edge sev-edge-${row.severity}`}
    />
  );
}

import { Link } from "react-router-dom";
import { Wrench } from "lucide-react";

import DataTable from "../ui/Table";
import { SeverityBadge, StatusBadge, ToolTag } from "../ui/Badge";
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
  showAssignee = true,
  emptyRow,
}) {
  const compact = variant === "wall";

  const columns = [
    {
      key: "severity",
      header: "Grav.",
      width: 76,
      render: (row) => <SeverityBadge severity={row.severity} short={compact} />,
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

  if (!compact) {
    columns.push({
      key: "cause",
      header: "Cause",
      width: 150,
      render: (row) => (
        <span style={{ color: "var(--ink-2)" }} title={row.cause_category ?? undefined}>
          {row.cause_label || row.cause_category || "—"}
        </span>
      ),
    });
  }

  columns.push({
    key: "description",
    header: "Description",
    wrap: false,
    render: (row) => (
      <span className="flex items-center gap-1.5" title={row.description ?? ""}>
        {row.is_maintenance && (
          <Wrench
            size={11}
            style={{ color: "var(--state-maintenance)" }}
            aria-label="Pendant une fenêtre de maintenance planifiée"
          />
        )}
        <span className="truncate-cell" style={{ color: "var(--ink-2)" }}>
          {ellipsis(row.description, compact ? 60 : 110)}
        </span>
      </span>
    ),
  });

  columns.push({
    key: "status",
    header: "Statut",
    width: 92,
    render: (row) => <StatusBadge status={row.status} />,
  });

  if (showAssignee && !compact) {
    columns.push({
      key: "assignee",
      header: "Affecté à",
      width: 140,
      render: (row) =>
        row.assigned_to_full_name ? (
          <span style={{ color: "var(--ink-2)" }}>{row.assigned_to_full_name}</span>
        ) : (
          // « Non affecté » en couleur d'alerte douce : c'est une file
          // que personne ne traite, pas une simple absence de valeur.
          <span style={{ color: "var(--sev-medium)" }}>Non affecté</span>
        ),
    });
  }

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
      render: (row) => <ToolTag tool={row.source_tool} />,
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

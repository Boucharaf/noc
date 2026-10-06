import { ChevronDown, ChevronUp } from "lucide-react";

/**
 * Tableau dense.
 *
 * Rendu direct, sans virtualisation : les listes sont paginées côté
 * serveur (200 lignes au maximum par page), et une grille virtualisée
 * casse la recherche du navigateur (Ctrl+F) — que les exploitants
 * utilisent en permanence pour retrouver un nom d'équipement.
 *
 * Chaque colonne est décrite par :
 *   key       identifiant unique
 *   header    libellé d'en-tête
 *   render    (row) => ReactNode
 *   align     "left" | "right" | "center"   (les nombres à droite)
 *   width     largeur CSS fixe
 *   sortKey   valeur à passer à onSort si la colonne est triable
 *   wrap      autorise le retour à la ligne (descriptions)
 */
export default function DataTable({
  columns,
  rows,
  rowKey = (row, index) => row.id ?? index,
  onRowClick,
  selectedKey,
  rowClassName,
  sort,
  onSort,
  dense = false,
  stickyHeader = true,
}) {
  const handleSort = (column) => {
    if (!column.sortKey || !onSort) return;
    onSort(column.sortKey);
  };

  return (
    <table className="tbl">
      <thead style={stickyHeader ? undefined : { position: "static" }}>
        <tr>
          {columns.map((column) => {
            const sortable = Boolean(column.sortKey && onSort);
            const active = sortable && sort?.key === column.sortKey;
            return (
              <th
                key={column.key}
                className={`${sortable ? "sortable" : ""} ${column.wrap ? "wrap" : ""}`}
                style={{
                  width: column.width,
                  textAlign: column.align ?? "left",
                }}
                onClick={() => handleSort(column)}
                aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : undefined}
              >
                <span className="inline-flex items-center gap-1">
                  {column.header}
                  {active &&
                    (sort.direction === "asc" ? (
                      <ChevronUp size={11} />
                    ) : (
                      <ChevronDown size={11} />
                    ))}
                </span>
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const key = rowKey(row, index);
          const extra = rowClassName?.(row) ?? "";
          return (
            <tr
              key={key}
              className={`${onRowClick ? "row-clickable" : ""} ${
                selectedKey !== undefined && selectedKey === key ? "row-selected" : ""
              } ${extra}`}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`${column.wrap ? "wrap" : ""} ${column.mono ? "num" : ""}`}
                  style={{
                    textAlign: column.align ?? "left",
                    height: dense ? 24 : undefined,
                  }}
                >
                  {column.render(row, index)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/** Pagination — affiche toujours le total, jamais seulement « page 2/7 ». */
export function Pagination({ page, pages, total, pageSize, onChange, label = "éléments" }) {
  if (!total) return null;
  const first = (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);

  return (
    <div
      className="flex items-center justify-between gap-3 px-2.5 py-1.5 border-t"
      style={{ borderColor: "var(--border)" }}
    >
      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
        <span className="num">{first}</span>–<span className="num">{last}</span> sur{" "}
        <span className="num" style={{ color: "var(--ink-2)" }}>
          {total}
        </span>{" "}
        {label}
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="btn btn-sm"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
        >
          Précédent
        </button>
        <span className="num text-[11.5px] px-1.5" style={{ color: "var(--ink-2)" }}>
          {page} / {pages}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
        >
          Suivant
        </button>
      </div>
    </div>
  );
}

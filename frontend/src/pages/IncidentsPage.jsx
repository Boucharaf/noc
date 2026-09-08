import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, FilterX } from "lucide-react";

import IncidentDrawer from "../components/domain/IncidentDrawer";
import IncidentTable from "../components/domain/IncidentTable";
import Panel from "../components/ui/Panel";
import { FilterSelect, Notice, SearchField, Segmented, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { Pagination } from "../components/ui/Table";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { SEVERITIES, STATUSES, severityMeta, statusMeta, toolLabel } from "../lib/vocabulary";
import { incidents as incidentsApi } from "../api/noc";
import { errorMessage } from "../api/client";
import { num } from "../lib/format";
import { saveBlob } from "../lib/download";
import { useIncidents, useReference } from "../hooks/queries";

/**
 * Historique et recherche d'incidents.
 *
 * Les filtres vivent dans l'URL et non dans un état local. C'est ce qui
 * permet de coller un lien « tous les critiques non acquittés de
 * Bobo-Dioulasso » dans une conversation d'astreinte, et de retrouver le
 * même écran au rechargement — un état local se perd au premier F5, au
 * milieu d'une investigation.
 *
 * Le paramètre `id` ouvre directement le tiroir de détail : c'est le lien
 * utilisé par le ticker d'alertes et par les notifications navigateur.
 */

const PAGE_SIZE = 50;

export default function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const { data: reference } = useReference();
  const [exportError, setExportError] = useState(null);
  const [exporting, setExporting] = useState(false);

  const selectedId = params.get("id") ? Number(params.get("id")) : null;
  const page = Number(params.get("page") ?? 1);

  const setParam = useCallback(
    (key, value) => {
      const next = new URLSearchParams(params);
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, String(value));
      // Tout changement de filtre ramène en page 1 : rester en page 7
      // d'un résultat qui n'en compte plus que 2 affiche un tableau vide
      // qu'on prend pour « aucun incident ».
      if (key !== "page" && key !== "id") next.delete("page");
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const filters = useMemo(() => {
    const value = {
      page,
      page_size: PAGE_SIZE,
      status: params.get("status") || undefined,
      severity: params.get("severity") || undefined,
      locality_id: params.get("locality_id") ? Number(params.get("locality_id")) : undefined,
      node_code: params.get("q") || undefined,
      source_tool: params.get("source_tool") || undefined,
      cause_category: params.get("cause") || undefined,
      date_from: params.get("from") || undefined,
      date_to: params.get("to") || undefined,
    };
    return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined));
  }, [params, page]);

  const query = useIncidents(filters);

  const activeFilterCount = ["status", "severity", "locality_id", "q", "source_tool", "cause", "from", "to"].filter(
    (key) => params.get(key),
  ).length;

  const exportCsv = async () => {
    setExportError(null);
    setExporting(true);
    try {
      const { page: _page, page_size: _pageSize, ...exportFilters } = filters;
      const blob = await incidentsApi.exportCsv({ ...exportFilters, limit: 5000 });
      await saveBlob(blob, `incidents-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (error) {
      setExportError(error.message || errorMessage(error));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Incidents"
        subtitle="Historique complet, filtrable et exportable"
        actions={
          <>
            {activeFilterCount > 0 && (
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setParams(selectedId ? { id: String(selectedId) } : {}, { replace: true })}
              >
                <FilterX size={13} /> Réinitialiser ({activeFilterCount})
              </button>
            )}
            <button type="button" className="btn btn-sm" onClick={exportCsv} disabled={exporting}>
              <Download size={13} /> {exporting ? "Export…" : "Export CSV"}
            </button>
          </>
        }
      />

      {exportError && (
        <Notice tone="error" onClose={() => setExportError(null)}>
          {exportError}
        </Notice>
      )}

      <Panel
        title="Recherche"
        flush
        bodyClassName=""
      >
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                <span className="num" style={{ color: "var(--ink-2)" }}>
                  {num(query.data?.total, "0")}
                </span>{" "}
                résultat{(query.data?.total ?? 0) > 1 ? "s" : ""}
              </span>
            }
          >
            <SearchField
              value={params.get("q") ?? ""}
              onChange={(value) => setParam("q", value)}
              placeholder="Nom d'équipement…"
              width={190}
            />
            <Segmented
              ariaLabel="Statut"
              value={params.get("status") ?? ""}
              onChange={(value) => setParam("status", value)}
              options={[
                { value: "", label: "Tous" },
                ...STATUSES.map((status) => ({
                  value: status,
                  label: statusMeta(status).label,
                })),
              ]}
            />
            <FilterSelect
              label="Gravité"
              value={params.get("severity")}
              onChange={(value) => setParam("severity", value)}
              allLabel="Toute gravité"
              width={132}
              options={SEVERITIES.filter((s) => s !== "unknown").map((severity) => ({
                value: severity,
                label: severityMeta(severity).label,
              }))}
            />
            <FilterSelect
              label="Site"
              value={params.get("locality_id")}
              onChange={(value) => setParam("locality_id", value)}
              allLabel="Tous les sites"
              width={160}
              options={(reference?.localities ?? []).map((locality) => ({
                value: locality.id,
                label: locality.name,
              }))}
            />
            <FilterSelect
              label="Cause"
              value={params.get("cause")}
              onChange={(value) => setParam("cause", value)}
              allLabel="Toute cause"
              width={170}
              options={(reference?.causes ?? []).map((cause) => ({
                value: cause.category,
                label: cause.label || cause.category,
              }))}
            />
            <FilterSelect
              label="Outil source"
              value={params.get("source_tool")}
              onChange={(value) => setParam("source_tool", value)}
              allLabel="Tous les outils"
              width={140}
              options={(reference?.source_tools ?? []).map((tool) => ({
                value: tool,
                label: toolLabel(tool),
              }))}
            />
            <input
              className="input"
              type="date"
              style={{ width: 138 }}
              value={params.get("from")?.slice(0, 10) ?? ""}
              onChange={(event) =>
                setParam("from", event.target.value ? `${event.target.value}T00:00:00` : "")
              }
              title="Détecté à partir du"
            />
            <input
              className="input"
              type="date"
              style={{ width: 138 }}
              value={params.get("to")?.slice(0, 10) ?? ""}
              onChange={(event) =>
                setParam("to", event.target.value ? `${event.target.value}T23:59:59` : "")
              }
              title="Détecté jusqu'au"
            />
          </Toolbar>
        </div>

        <div style={{ maxHeight: "calc(100vh - 260px)", overflow: "auto" }}>
          <QueryBoundary
            query={query}
            skeleton={<SkeletonRows rows={10} columns={7} />}
            empty={(data) => !data?.items?.length}
            emptyMessage="Aucun incident ne correspond à ces filtres"
            emptyHint={
              activeFilterCount
                ? "Élargissez la période ou retirez un filtre."
                : "Aucun incident n'a encore été collecté sur cette période."
            }
          >
            {(data) => (
              <IncidentTable
                incidents={data.items}
                selectedId={selectedId}
                onSelect={(row) => setParam("id", row.id)}
              />
            )}
          </QueryBoundary>
        </div>

        {query.data && (
          <Pagination
            page={query.data.page}
            pages={query.data.pages}
            total={query.data.total}
            pageSize={query.data.page_size}
            onChange={(next) => setParam("page", next)}
            label="incidents"
          />
        )}
      </Panel>

      <IncidentDrawer
        incidentId={selectedId}
        open={Boolean(selectedId)}
        onClose={() => setParam("id", null)}
      />
    </div>
  );
}

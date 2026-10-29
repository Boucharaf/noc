import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Download, FilterX } from "lucide-react";

import AlertDrawer from "../components/domain/AlertDrawer";
import IncidentTable from "../components/domain/IncidentTable";
import Panel from "../components/ui/Panel";
import { FilterSelect, Notice, SearchField, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { Pagination } from "../components/ui/Table";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { SEVERITIES, TOOL_LABEL, severityMeta, toolLabel } from "../lib/vocabulary";
import { incidents as incidentsApi } from "../api/noc";
import { errorMessage } from "../api/client";
import { num } from "../lib/format";
import { saveBlob } from "../lib/download";
import { useAlertAges, useAlertsByTool, useIncidents } from "../hooks/queries";

/**
 * Alertes des OUTILS de supervision — Zabbix, Centreon, NetXMS, Nagios, NSP.
 *
 * Ce ne sont pas des incidents : un incident est un ticket iTop (écran
 * Incidents iTop). Les tickets iTop sont donc exclus de cette liste.
 *
 * Le périmètre (région, province, site, recherche) vient de la barre
 * commune ; la localité n'est donc plus un filtre propre à cet écran.
 *
 * Les filtres vivent dans l'URL et non dans un état local. On peut ainsi
 * partager une file par site, gravité ou acquittement et retrouver le même
 * écran au rechargement — un état local se perd au premier F5.
 *
 * Le paramètre `id` ouvre directement le tiroir de détail depuis un lien
 * de notification ou un partage d'investigation.
 */

const PAGE_SIZE = 50;

export default function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const [exportError, setExportError] = useState(null);
  const [exporting, setExporting] = useState(false);

  const ages = useAlertAges();
  const byTool = useAlertsByTool();

  const selectedId = params.get("id") || null;
  const page = Number(params.get("page") ?? 1);

  const setParam = useCallback(
    (key, value) => {
      const next = new URLSearchParams(params);
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, String(value));
      if (key === "site") next.delete("locality_id");
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
      severity: params.get("severity") || undefined,
      site: params.get("site") || params.get("locality_id") || undefined,
      acknowledged: params.has("acknowledged") ? params.get("acknowledged") : undefined,
      node_code: params.get("q") || undefined,
      source_tool: params.get("source_tool") || undefined,
      exclude_itsm: true,
      date_from: params.get("from") || undefined,
      date_to: params.get("to") || undefined,
    };
    return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined));
  }, [params, page]);

  const query = useIncidents(filters);

  const activeFilterCount = ["severity", "acknowledged", "q", "source_tool", "from", "to"].filter(
    (key) => params.get(key),
  ).length;

  const exportCsv = async () => {
    setExportError(null);
    setExporting(true);
    try {
      const { page: _page, page_size: _pageSize, ...exportFilters } = filters;
      const blob = await incidentsApi.exportCsv({ ...exportFilters, limit: 5000 });
      await saveBlob(blob, `alertes-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (error) {
      setExportError(error.message || errorMessage(error));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Alertes des outils"
        subtitle="Signaux techniques de Zabbix, Centreon, NetXMS, Nagios et NSP — les incidents sont tenus dans iTop"
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

      <div className="grid grid-cols-12 gap-2 items-start">
        <Panel
          title="Depuis combien de temps durent les alertes en cours ?"
          subtitle="en rouge : la part des alertes critiques"
          className="col-span-12 xl:col-span-8"
        >
          <QueryBoundary query={ages} compact empty={(d) => !d?.some((b) => b.count)} emptyMessage="Aucune alerte en cours">
            {(buckets) => {
              const max = Math.max(1, ...buckets.map((b) => b.count));
              const colors = {
                lt1h: "var(--sev-medium)",
                lt24h: "var(--sev-high)",
                lt7d: "var(--accent)",
                lt30d: "var(--ink-2)",
                gt30d: "var(--ink-3)",
              };
              return (
                <ul className="space-y-2">
                  {buckets.map((bucket) => (
                    <li key={bucket.key}>
                      <div className="flex items-baseline gap-2 text-[12.5px]">
                        <span className="flex-1">{bucket.label}</span>
                        {bucket.critical > 0 && (
                          <span className="text-[11px]" style={{ color: "var(--sev-critical)" }}>
                            {num(bucket.critical)} critique(s)
                          </span>
                        )}
                        <span className="num font-semibold" style={{ minWidth: 40, textAlign: "right" }}>
                          {num(bucket.count)}
                        </span>
                      </div>
                      <div className="relative h-[9px] rounded-full mt-1" style={{ background: "var(--surface-3)" }}>
                        <div
                          className="absolute left-0 top-0 bottom-0 rounded-full"
                          style={{ width: `${(100 * bucket.count) / max}%`, background: colors[bucket.key] }}
                        />
                        <div
                          className="absolute left-0 top-0 bottom-0 rounded-full"
                          style={{ width: `${(100 * bucket.critical) / max}%`, background: "var(--sev-critical)" }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              );
            }}
          </QueryBoundary>
        </Panel>
        <Panel title="Par outil" subtitle="alertes actives · clic pour filtrer" className="col-span-12 xl:col-span-4">
          <QueryBoundary query={byTool} compact empty={(d) => !d?.length} emptyMessage="Aucune alerte">
            {(rows) => {
              const max = Math.max(1, ...rows.map((row) => row.count));
              return (
                <ul className="space-y-1.5">
                  {rows.map((row) => (
                    <li key={row.tool}>
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => setParam("source_tool", params.get("source_tool") === row.tool ? "" : row.tool)}
                      >
                        <div className="flex items-baseline text-[12px]">
                          <span
                            className="flex-1"
                            style={{ fontWeight: params.get("source_tool") === row.tool ? 600 : undefined }}
                          >
                            {toolLabel(row.tool)}
                          </span>
                          <span className="num">{num(row.count)}</span>
                        </div>
                        <div className="h-[7px] rounded-full mt-1" style={{ background: "var(--surface-3)" }}>
                          <div
                            className="h-full rounded-full"
                            style={{ width: `${(100 * row.count) / max}%`, background: "var(--accent)" }}
                          />
                        </div>
                      </button>
                    </li>
                  ))}
                </ul>
              );
            }}
          </QueryBoundary>
        </Panel>
      </div>

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
              suggest="alert"
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
              label="Acquittement"
              value={params.get("acknowledged")}
              onChange={(value) => setParam("acknowledged", value)}
              allLabel="Tous"
              width={145}
              options={[
                { value: "false", label: "Non acquittées (outil)" },
                { value: "true", label: "Acquittées (outil)" },
              ]}
            />
            <FilterSelect
              label="Outil source"
              value={params.get("source_tool")}
              onChange={(value) => setParam("source_tool", value)}
              allLabel="Tous les outils"
              width={140}
              // Outils de SUPERVISION seulement : iTop produit des incidents.
              options={Object.keys(TOOL_LABEL)
                .filter((tool) => tool !== "itop")
                .map((tool) => ({ value: tool, label: toolLabel(tool) }))}
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
            emptyMessage="Aucune alerte ne correspond à ces filtres"
            emptyHint={
              activeFilterCount
                ? "Élargissez la période ou retirez un filtre."
                : "Aucune alerte active dans ce périmètre."
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
            label="alertes"
          />
        )}
      </Panel>

      <AlertDrawer
        alertKey={selectedId}
        open={Boolean(selectedId)}
        onClose={() => setParam("id", null)}
      />
    </div>
  );
}

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { FilterX } from "lucide-react";

import NodeTable from "../components/domain/NodeTable";
import Panel from "../components/ui/Panel";
import { FilterSelect, SearchField, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { Pagination } from "../components/ui/Table";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { NODE_STATES, TOOL_LABEL, nodeStateMeta, toolLabel } from "../lib/vocabulary";
import { num } from "../lib/format";
import { useNodes, useOverview } from "../hooks/queries";

/**
 * Inventaire du parc.
 *
 * La rangée de compteurs en tête n'est pas un résumé décoratif : ce sont
 * des FILTRES. Cliquer sur « Muets 14 » affiche les quatorze
 * équipements dont plus aucun outil ne remonte de mesure — le geste que
 * fait un exploitant qui soupçonne une panne de collecte, et qui
 * demandait auparavant de trier une liste à la main.
 *
 * L'état « Muet » mérite un mot : il ne veut pas dire « en panne ». Il
 * veut dire « on ne sait plus ». C'est précisément l'angle mort que les
 * tableaux de bord classiques comptent comme « OK ».
 */

const PAGE_SIZE = 50;

export default function NodesPage() {
  const [params, setParams] = useSearchParams();
  // Décomptes par état DU PÉRIMÈTRE courant (barre commune), pas du pays.
  const overview = useOverview();

  const setParam = useCallback(
    (key, value) => {
      const next = new URLSearchParams(params);
      if (value === null || value === undefined || value === "") next.delete(key);
      else next.set(key, String(value));
      if (key !== "page") next.delete("page");
      setParams(next, { replace: true });
    },
    [params, setParams],
  );

  const filters = useMemo(() => {
    const value = {
      page: Number(params.get("page") ?? 1),
      page_size: PAGE_SIZE,
      q: params.get("q") || undefined,
      state: params.get("state") || undefined,
      // Région, province et site viennent de la barre de périmètre.
      tool: params.get("source_tool") || undefined,
      sort: params.get("sort") || "state",
    };
    return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined));
  }, [params]);

  const query = useNodes(filters);
  const counts = overview.data
    ? { ...overview.data.nodes_by_state, total: overview.data.nodes_total }
    : undefined;
  const activeState = params.get("state");

  const activeFilters = ["q", "state", "source_tool"].filter(
    (key) => params.get(key),
  ).length;

  const sort = { key: filters.sort, direction: "asc" };

  return (
    <div className="space-y-2.5">
      <PageHeader
        title="Équipements"
        subtitle="Parc supervisé, état courant et dernières mesures"
        actions={
          activeFilters > 0 && (
            <button type="button" className="btn btn-sm" onClick={() => setParams({}, { replace: true })}>
              <FilterX size={13} /> Réinitialiser ({activeFilters})
            </button>
          )
        }
      />

      {/* --- Compteurs cliquables --- */}
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        <button
          type="button"
          className="panel px-2.5 py-2 text-left"
          style={{
            borderColor: !activeState ? "var(--border-strong)" : "var(--border)",
          }}
          onClick={() => setParam("state", null)}
        >
          <div className="text-[10.5px] uppercase tracking-[0.07em]" style={{ color: "var(--ink-3)" }}>
            Parc total
          </div>
          <div className="num font-semibold" style={{ fontSize: 20 }}>
            {num(counts?.total, "—")}
          </div>
        </button>

        {NODE_STATES.map((state) => {
          const meta = nodeStateMeta(state);
          const active = activeState === state;
          const value = counts?.[state] ?? 0;
          return (
            <button
              key={state}
              type="button"
              className="panel px-2.5 py-2 text-left"
              title={meta.hint}
              style={{
                borderColor: active ? meta.color : "var(--border)",
                background: active
                  ? `color-mix(in srgb, ${meta.color} 10%, var(--surface))`
                  : undefined,
              }}
              onClick={() => setParam("state", active ? null : state)}
            >
              <div
                className="text-[10.5px] uppercase tracking-[0.07em] flex items-center gap-1"
                style={{ color: "var(--ink-3)" }}
              >
                <span className="dot" style={{ background: meta.color, width: 6, height: 6 }} />
                {meta.label}
              </div>
              <div
                className="num font-semibold"
                style={{ fontSize: 20, color: value ? meta.color : "var(--ink-3)" }}
              >
                {num(value, "0")}
              </div>
            </button>
          );
        })}
      </div>

      <Panel title="Inventaire" flush>
        <div className="p-2 border-b" style={{ borderColor: "var(--border)" }}>
          <Toolbar
            right={
              <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                <span className="num" style={{ color: "var(--ink-2)" }}>
                  {num(query.data?.total, "0")}
                </span>{" "}
                équipement{(query.data?.total ?? 0) > 1 ? "s" : ""}
              </span>
            }
          >
            <SearchField
              value={params.get("q") ?? ""}
              onChange={(value) => setParam("q", value)}
              placeholder="Nom ou adresse IP…"
              width={190}
              suggest="node"
            />
            <FilterSelect
              label="État"
              value={params.get("state")}
              onChange={(value) => setParam("state", value)}
              allLabel="Tous les états"
              width={140}
              options={NODE_STATES.map((state) => ({
                value: state,
                label: nodeStateMeta(state).label,
              }))}
            />
            <FilterSelect
              label="Supervisé par"
              value={params.get("source_tool")}
              onChange={(value) => setParam("source_tool", value)}
              allLabel="Tous les outils"
              width={140}
              options={Object.keys(TOOL_LABEL)
                .filter((tool) => tool !== "manual")
                .map((tool) => ({ value: tool, label: toolLabel(tool) }))}
            />
          </Toolbar>
        </div>

        <div style={{ maxHeight: "calc(100vh - 300px)", overflow: "auto" }}>
          <QueryBoundary
            query={query}
            skeleton={<SkeletonRows rows={10} columns={8} />}
            empty={(data) => !data?.items?.length}
            emptyMessage="Aucun équipement ne correspond"
            emptyHint={
              activeFilters
                ? "Retirez un filtre pour élargir la recherche."
                : "Aucun équipement dans l'inventaire pour l'instant."
            }
          >
            {(data) => (
              <NodeTable
                nodes={data.items}
                sort={sort}
                onSort={(key) => setParam("sort", key)}
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
            label="équipements"
          />
        )}
      </Panel>
    </div>
  );
}

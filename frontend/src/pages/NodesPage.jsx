import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { FilterX } from "lucide-react";

import NodeTable from "../components/domain/NodeTable";
import Panel from "../components/ui/Panel";
import { FilterSelect, SearchField, Toolbar } from "../components/ui/Controls";
import { PageHeader } from "../components/layout/TopBar";
import { Pagination } from "../components/ui/Table";
import { QueryBoundary, SkeletonRows } from "../components/ui/States";
import { NODE_STATES, nodeStateMeta, toolLabel } from "../lib/vocabulary";
import { num } from "../lib/format";
import { useNodeStates, useNodes, useReference } from "../hooks/queries";

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
  const { data: reference } = useReference();
  const stateCounts = useNodeStates();

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
      locality_id: params.get("locality_id") ? Number(params.get("locality_id")) : undefined,
      region_id: params.get("region_id") ? Number(params.get("region_id")) : undefined,
      ministry_id: params.get("ministry_id") ? Number(params.get("ministry_id")) : undefined,
      node_type: params.get("node_type") || undefined,
      source_tool: params.get("source_tool") || undefined,
      sort: params.get("sort") || "state",
    };
    return Object.fromEntries(Object.entries(value).filter(([, v]) => v !== undefined));
  }, [params]);

  const query = useNodes(filters);
  const counts = stateCounts.data;
  const activeState = params.get("state");

  const activeFilters = ["q", "state", "locality_id", "region_id", "ministry_id", "node_type", "source_tool"].filter(
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
            />
            <FilterSelect
              label="Région"
              value={params.get("region_id")}
              onChange={(value) => setParam("region_id", value)}
              allLabel="Toutes régions"
              width={150}
              options={(reference?.regions ?? []).map((region) => ({
                value: region.id,
                label: region.name,
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
              label="Ministère"
              value={params.get("ministry_id")}
              onChange={(value) => setParam("ministry_id", value)}
              allLabel="Tous ministères"
              width={190}
              options={(reference?.ministries ?? []).map((ministry) => ({
                value: ministry.id,
                label: ministry.name,
              }))}
            />
            <FilterSelect
              label="Type"
              value={params.get("node_type")}
              onChange={(value) => setParam("node_type", value)}
              allLabel="Tous types"
              width={120}
              options={(reference?.node_types ?? []).map((type) => ({ value: type, label: type }))}
            />
            <FilterSelect
              label="Supervisé par"
              value={params.get("source_tool")}
              onChange={(value) => setParam("source_tool", value)}
              allLabel="Tous les outils"
              width={140}
              options={(reference?.source_tools ?? []).map((tool) => ({
                value: tool,
                label: toolLabel(tool),
              }))}
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
                : "L'inventaire est vide : dim_node n'est peuplée que par la collecte ETL."
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

# load/

Écriture dans l'entrepôt PostgreSQL + TimescaleDB (schéma défini dans
`sql/`). Toutes les opérations sont des upserts idempotents : rejouer un
lot déjà chargé ne duplique rien (clé `(source_tool, external_id)` pour
les faits, `(source_tool, external_ref)` pour la correspondance de nœuds).

| Fichier | Rôle |
|---|---|
| `load_dimensions.py` | upsert `dim_node` + `dim_node_source_map` (fusion multi-outils déjà résolue en amont par `transform/identity_resolution.py`) |
| `load_facts.py` | upsert `fact_incident`, recalcul quotidien de `fact_supervision_coverage_daily` |
| `load_metrics_timescale.py` | insertion par lots dans la hypertable `metric_value` |

Une métrique ou un incident référençant un nœud pas encore connu de
`dim_node_source_map` est ignoré silencieusement (log, pas d'exception) :
l'ordre de chargement dans `pipelines/collector.py` charge toujours les
nœuds avant les faits/métriques, ce cas ne devrait donc être qu'un filet
de sécurité, pas la normale.

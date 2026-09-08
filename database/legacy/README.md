# Schéma obsolète — ne pas exécuter

Ces fichiers appartiennent à la **version 1** de la plateforme, celle qui
utilisait une base `noc_db` distincte alimentée par
`POST /api/incidents/ingest`. Ce modèle n'existe plus : l'ETL écrit
désormais directement dans l'entrepôt unique.

| Fichier | Ce que c'était |
|---|---|
| `01_schema.sql` | ancien schéma complet (`dim_asset`, `dim_cause` avec `cause_id`, `fact_metric`, `dim_province`, `dim_organisation`…) |
| `02_kpi_extensions.sql` | vue matérialisée `mv_kpi_node_monthly` et ses index, supprimés en v2 |
| `01_backend_extensions.sql` | copie de `backend/sql/01_backend_extensions.sql` |
| `generate_seed.py` | générateur de données pour l'ancien schéma |

## Pourquoi ils ont été déplacés ici

`docker-compose.yml` montait le répertoire `database/` entier dans
`/docker-entrypoint-initdb.d` du conteneur PostgreSQL. Au premier
démarrage sur une base vide, PostgreSQL exécute **tout** ce qu'il y trouve,
par ordre alphabétique — donc l'ancien schéma, puis les extensions de
l'ancien schéma, puis le dump NetXMS de 370 Mo, sur la base du dashboard.

Le résultat : un démarrage interminable suivi d'un schéma incohérent où
coexistaient les tables des deux versions.

Le compose monte désormais les quatre fichiers corrects un par un, dans
l'ordre imposé par leurs dépendances :

```yaml
- ./etl/sql/schema_dimensions.sql:/docker-entrypoint-initdb.d/10_dimensions.sql:ro
- ./etl/sql/schema_facts.sql:/docker-entrypoint-initdb.d/20_facts.sql:ro
- ./etl/sql/schema_timescale.sql:/docker-entrypoint-initdb.d/30_timescale.sql:ro
- ./backend/sql/01_backend_extensions.sql:/docker-entrypoint-initdb.d/40_backend.sql:ro
```

## Le schéma actuel

* `etl/sql/schema_dimensions.sql` — `dim_ministry`, `dim_region`,
  `dim_locality`, `dim_node`, `dim_link`, `dim_node_source_map`,
  `dim_cause`, `dim_user`
* `etl/sql/schema_facts.sql` — `fact_incident`,
  `fact_supervision_coverage_daily`
* `etl/sql/schema_timescale.sql` — hypertable `metric_value`, agrégat
  continu `metric_hourly`, rétention et compression
* `backend/sql/01_backend_extensions.sql` — vues `v_node` / `v_incident`,
  fonctions de normalisation, tables `ops_*`

Ce répertoire est conservé pour référence historique (retrouver comment
une donnée était modélisée avant la migration). Il ne doit être exécuté
sur aucune base.

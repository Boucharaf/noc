# sql/

DDL de l'entrepôt, à appliquer dans cet ordre lors de l'initialisation :

1. `schema_dimensions.sql`
2. `schema_facts.sql` (référence les dimensions)
3. `schema_timescale.sql` (référence `dim_node`/`dim_link`, active l'extension TimescaleDB)

```bash
psql "$NOC_WAREHOUSE_DSN" -f schema_dimensions.sql
psql "$NOC_WAREHOUSE_DSN" -f schema_facts.sql
psql "$NOC_WAREHOUSE_DSN" -f schema_timescale.sql
```

## Découpage géographique : volontairement souple

`dim_ministry`, `dim_region` et `dim_locality` n'imposent aucune
hiérarchie stricte a priori (`external_ref` nullable, pas de contrainte
NOT NULL sur les clés étrangères de `dim_node`). Le découpage réel
(ministère → région → localité → site) sera peuplé à partir de ce que
les API renvoient effectivement (groupes Zabbix/Centreon, org_id/location_id
iTop) via `scripts/discover_geography.py`, pas imposé par ce schéma à
l'avance — conformément à la demande de se baser sur les documentations
plutôt que sur une structure supposée.

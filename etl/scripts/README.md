# scripts/

Utilitaires ponctuels, exécutés manuellement (pas par Celery).

| Fichier | Rôle |
|---|---|
| `restore_source_db.py` | restaure un dump pg_dump d'un outil dans un schéma de staging (`staging_<outil>`), préalable à l'activation de `<OUTIL>_DB_RESTORE_ENABLED` |
| `discover_geography.py` | peuple `dim_ministry`/`dim_region`/`dim_locality` à partir de ce que les API renvoient réellement (Organization/Location iTop en priorité, groupes Zabbix/Centreon en repli) — **aucune** liste de régions codée en dur |

## Pourquoi pas de script de provisionnement de nœuds séparé ?

Contrairement à l'ancien projet, `load/load_dimensions.py` upserte déjà
les nœuds à chaque cycle de collecte (`ON CONFLICT ... DO UPDATE`) : un
script `provision_nodes.py` séparé n'a plus de raison d'être, la première
collecte fait le travail. Ce choix simplifie délibérément l'arborescence
par rapport à la version précédente du projet.

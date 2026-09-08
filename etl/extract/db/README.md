# extract/db/

Lecteurs en lecture seule sur des BDD sources **restaurées via pg_dump /
pg_restore** dans des schémas de staging PostgreSQL dédiés (un schéma par
outil). Toujours secondaires par rapport à `extract/api/`, sauf pour
Nagios si aucune API n'est confirmée disponible (voir plus bas).

## Principe

- Chaque lecteur expose la même interface que son connecteur API
  (`fetch_nodes`, `fetch_incidents`, `fetch_metrics`) et retourne le même
  schéma normalisé.
- Activé uniquement par `<OUTIL>_DB_RESTORE_ENABLED=true` + `<OUTIL>_DB_DSN`
  dans la config (`config.py`).
- Sa sortie ne remplace jamais l'API : elle passe par `transform/dedup.py`
  qui ne garde que ce que l'API n'a pas déjà donné.
- Si la base source native n'est pas PostgreSQL (Centreon, iTop, Nagios
  NDOUtils sont nativement MySQL/MariaDB), une conversion vers un schéma
  Postgres compatible doit être faite au moment de la restauration (voir
  `scripts/restore_source_db.py`) — ce n'est pas le rôle de ces lecteurs.

## Cas particulier Nagios

Si l'agence confirme qu'aucune API (Livestatus, Nagios XI) n'est
disponible, `nagios_db_reader.py` (schéma NDOUtils) devient la seule
source pour cet outil — dans ce cas précis il est activé en continu, pas
seulement en complément.

## Schémas à valider avant mise en production

Les noms de tables/colonnes utilisés ici (Zabbix, iTop, NetXMS, Centreon,
NDOUtils) correspondent aux schémas standards documentés de chaque outil.
Toute personnalisation côté agence (tables renommées, préfixes différents,
datamodel iTop étendu) devra être vérifiée sur les dumps réels avant de
faire confiance à ces requêtes en production.

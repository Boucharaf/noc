# ETL NOC RESINA

Collecte, unifie et charge les données de supervision de 6 outils
(Zabbix, iTop, NetXMS, Centreon, Nagios, Nokia NSP) vers un entrepôt
unique PostgreSQL + TimescaleDB, consommé ensuite par le backend puis le
frontend du NOC.

**Reconstruit intégralement à partir des documentations API des 6
outils — aucun fichier, logique ou hypothèse de l'ancien projet ETL n'a
été repris.**

## Principes

1. **Les API sont la seule source obligatoire.** Le système fonctionne
   entièrement sans aucune base restaurée.
2. **La restauration de BDD (pg_dump) est un bonus optionnel**, activable
   outil par outil, qui ne fait qu'ajouter ce que l'API n'a pas — jamais
   d'écrasement (voir `transform/dedup.py`).
3. **Un entrepôt unique**, PostgreSQL + TimescaleDB, où toutes les
   données des 6 outils convergent vers le même schéma normalisé, quelle
   que soit leur origine.
4. **Découpage géographique déduit des données**, pas imposé à l'avance
   (voir `scripts/discover_geography.py`).

## Démarrage

```bash
cp .env.example .env      # renseigner les identifiants API réels
pip install -r requirements.txt

# 1. schéma de l'entrepôt
psql "$NOC_WAREHOUSE_DSN" -f sql/schema_dimensions.sql
psql "$NOC_WAREHOUSE_DSN" -f sql/schema_facts.sql
psql "$NOC_WAREHOUSE_DSN" -f sql/schema_timescale.sql

# 2. lancer la collecte planifiée
celery -A etl.celery_app worker --loglevel=info &
celery -A etl.celery_app beat --loglevel=info &

# ou déclencher un cycle manuellement :
python -c "from etl.pipelines.tasks import collect_all_tools; collect_all_tools()"
```

## Arborescence

```
etl/
├── config.py            # toute la configuration (variables d'env), voir .env.example
├── celery_app.py         # déclaration Celery + planification
├── report_trigger.py     # point d'intégration avec le reporting du backend (à finaliser)
├── extract/
│   ├── api/               # connecteurs API — source obligatoire (README dédié)
│   └── db/                # lecteurs BDD restaurées — source optionnelle (README dédié)
├── transform/             # normalisation, réconciliation, classification (README dédié)
├── load/                  # écriture dans l'entrepôt (README dédié)
├── pipelines/
│   ├── collector.py       # orchestration extract -> dedup -> transform -> load, par outil
│   ├── tasks.py            # tâches Celery, seul endroit qui instancie les connecteurs concrets
│   └── status.py           # statut de collecte publié dans Redis
├── scripts/               # utilitaires manuels : restauration pg_dump, découverte géographique (README dédié)
├── sql/                   # DDL de l'entrepôt (README dédié)
└── tests/
```

## État des lieux et points en attente

| Outil | Statut |
|---|---|
| Zabbix, iTop, NetXMS, Centreon | ✅ connecteurs API fonctionnels |
| Nagios | ⚠️ 3 modes déjà codés (Livestatus / Nagios XI / NDOUtils-BDD) ; `NAGIOS_MODE` à fixer une fois la variante confirmée par l'agence |
| Nokia NSP | ⚠️ connecteur créé (Fault Management "classic" et "yang") ; version NSP et endpoint de Performance Management à confirmer |

Voir `extract/api/README.md` pour le détail des deux points en attente,
et `sql/README.md` pour la logique du découpage géographique.

## Prochaine étape

Une fois ce paquet ETL validé : adaptation du backend et du frontend
existants (fournis séparément) à ce nouveau schéma d'entrepôt.

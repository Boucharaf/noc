# Plateforme NOC RESINA

Centre de supervision du réseau de l'administration burkinabè. La
plateforme agrège six outils hétérogènes (Zabbix, iTop, NetXMS, Centreon,
Nagios, Nokia NSP) dans un entrepôt unique, et en tire quatre tableaux de
bord — un par métier.

```
┌──────────────┐   collecte    ┌───────────────────────┐    lecture    ┌───────────────┐
│  6 outils    │──────────────▶│  Entrepôt PostgreSQL  │◀─────────────│   Backend     │
│  supervision │   (Celery,    │  + TimescaleDB        │   (SQL seul)  │   FastAPI     │
│  et ITSM     │    5 min)     │                       │──────────────▶│  70 endpoints │
└──────────────┘               │  dim_* fact_* metric_*│    écriture   └───────┬───────┘
                               │  ops_* (backend)      │    ops_*              │
        ETL ────────────────── └───────────────────────┘                       │ REST + WebSocket
                                                                               ▼
                                                                       ┌───────────────┐
                                                                       │   Frontend    │
                                                                       │  React / Vite │
                                                                       └───────────────┘
```

**Un seul entrepôt.** L'ETL écrit, le backend lit — plus aucune ingestion
par HTTP. C'est le changement structurel de la version 2 : l'ancien
backend supposait que l'ETL lui poussait chaque incident, ce qui créait
deux chemins d'écriture concurrents sur la même table.

---

## 1. Démarrage en cinq minutes

### Avec Docker (recommandé)

```bash
cp .env.example .env
# Renseigner AU MINIMUM : SECRET_KEY, INTERNAL_API_KEY, POSTGRES_PASSWORD
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up -d --build

# Créer le premier compte (aucun n'existe au départ)
docker compose exec backend python scripts/create_user.py \
    --demo-set --password "MotDePasse123"

# Données de démonstration, pour voir les écrans vivre
docker compose exec backend python scripts/seed_demo.py
```

Puis <https://localhost:8443> (certificat auto-signé : accepter
l'avertissement) ou <http://localhost:8888>.

Comptes créés par `--demo-set`, un par tableau de bord :

| Identifiant | Rôle | Écran d'accueil |
|---|---|---|
| `directeur` | Directeur | Pilotage RESINA |
| `chefnoc` | Chef NOC | Salle de supervision |
| `technicien` | Technicien | Console d'exploitation |
| `terrain` | Agent terrain | Tournée |

### Sans Docker

```bash
# 1. Entrepôt — PostgreSQL 15+ AVEC l'extension TimescaleDB
createdb noc_warehouse
export NOC_WAREHOUSE_DSN=postgresql://noc:noc@localhost:5432/noc_warehouse

# L'ordre compte : l'extension backend référence les tables de l'ETL
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_dimensions.sql
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_facts.sql
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_timescale.sql
psql "$NOC_WAREHOUSE_DSN" -f backend/sql/01_backend_extensions.sql

# 2. Backend
cd backend && pip install -r requirements.txt
python scripts/create_user.py --demo-set --password "MotDePasse123"
uvicorn app.main:app --port 8000

# 3. Frontend
cd frontend && npm install && npm run dev

# 4. ETL (facultatif tant qu'aucun outil n'est configuré)
cd etl && pip install -r requirements.txt
celery -A etl.celery_app worker --loglevel=INFO
celery -A etl.celery_app beat   --loglevel=INFO
```

---

## 2. Ce qui a été corrigé dans cette itération

La refonte du frontend a mis au jour plusieurs points qui empêchaient le
projet de démarrer tel quel. Ils sont corrigés :

| Problème | Conséquence | Correction |
|---|---|---|
| `docker-compose.yml` montait `./database` dans `docker-entrypoint-initdb.d` | Au premier démarrage, PostgreSQL exécutait l'**ancien schéma** puis un dump NetXMS de **370 Mo** sur la base du dashboard | Les quatre DDL corrects sont montés un par un, dans l'ordre. Les fichiers obsolètes sont déplacés dans `database/legacy/` |
| Image `postgres:15-alpine` | `CREATE EXTENSION timescaledb` échoue → **aucune métrique** ne peut être stockée | Image `timescale/timescaledb:2.17.2-pg16` |
| Variables `DB_HOST`, `NOC_API_KEY`, `SYNC_MV_REFRESH`, `ZABBIX_USER`… | Plus lues par personne : le backend et l'ETL cherchaient `NOC_WAREHOUSE_DSN`, `INTERNAL_API_KEY`, `ZABBIX_API_USER`… et repartaient sur leurs défauts | Variables alignées sur `backend/app/core/config.py` et `etl/config.py` |
| `etl/Dockerfile` absent | `docker compose build` échouait | Recréé. Le paquet est copié dans `/app/etl` et les commandes visent `etl.celery_app` — les modules utilisent des imports relatifs |
| `backend/docker-images/` supprimé mais toujours référencé | `docker compose up` échouait sur la construction de NetXMS et Centreon | Les 11 services d'outils sont passés sous le profil `tools` : ils ne démarrent plus par défaut |
| `frontend/nginx.conf` ne relayait ni `/api` ni `/ws` | Le conteneur frontend n'était utilisable que derrière la passerelle | Relais ajouté, plus gzip et politique de cache (`sw.js` jamais mis en cache) |
| `etl/report_trigger.py` portait un `TODO` | Le rapport mensuel automatique n'était **jamais** produit | Implémenté, avec repli silencieux : un backend injoignable ne fait pas échouer la collecte |
| Aucun moyen de créer le premier compte | Impossible de se connecter à une installation neuve | `backend/scripts/create_user.py` |
| Entrepôt vide = tous les écrans vides | Impossible de valider ou démontrer l'interface | `backend/scripts/seed_demo.py` |
| `celery_app.py` sans `include` | Le worker démarrait « sain » puis **rejetait chaque tâche** de beat (`Received unregistered task`) : l'ETL ne collectait **rien** | `include=["etl.pipelines.tasks"]` — le planificateur ne connaît que des noms, c'est au worker d'avoir importé les fonctions |
| `backend/Dockerfile` ne copiait pas `scripts/` | `docker compose exec backend python scripts/create_user.py` échouait : impossible d'amorcer le premier compte | `COPY scripts ./scripts` |
| `ON CONFLICT` sur un index **partiel** dans le semis | La création des fenêtres de maintenance échouait | Prédicat `WHERE source_tool IS NOT NULL` répété dans la clause |
| Ordre de purge du semis | Violation de `dim_node_source_map_node_id_fkey` | Identifiants relevés avant de vider la table de correspondance |
| `alerts.length` sur une valeur non encore chargée | **Écran blanc total** sur la console du technicien | Lecture via le tableau memoïsé, plus une **frontière d'erreur** : un écran qui plante n'emporte plus la barre d'état ni la navigation |
| « Votre session a expiré » à la première visite | Message d'expiration pour une session qui n'a jamais existé | `refresh({ silent: true })` au démarrage |

Tous ces points ont été trouvés **en exécutant la pile**, pas en relisant
le code : c'est la raison d'être de la campagne de vérification décrite
au §7.

### Ce qui reste à faire côté agence

* **`NAGIOS_MODE`** (`livestatus` | `xi` | `ndoutils`) et **`NSP_FM_MODE`**
  (`classic` | `yang`) sont à confirmer. Tant qu'ils valent `unknown`, ces
  deux connecteurs ne collectent rien et l'écran « Collecte ETL » l'indique.
* **`etl/scripts/discover_geography.py`** doit tourner au moins une fois,
  sinon `dim_region`, `dim_locality` et `dim_ministry` restent vides : la
  carte n'affiche rien et le classement par ministère est vide. Ce n'est
  pas une erreur, et l'interface le dit explicitement.
* Le profil `tools` a besoin de `backend/docker-images/` pour NetXMS et
  Centreon. Restaurer si nécessaire : `git checkout backend/docker-images`.

---

## 3. Les quatre profils

L'architecture reprend les quatre niveaux du document métier
« informations essentielles par profil ». **Chaque rôle a son écran**, et
non un écran commun filtré.

| Niveau | Rôle | Route | Contenu |
|---|---|---|---|
| 1 | Directeur | `/direction` | Disponibilité globale, SLA, MTTR, incidents critiques, Top 10 sites, tendance 6 mois, ministères, causes, couverture, rapports. **Aucune action d'exploitation** |
| 2 | Chef NOC | `/supervision` | État du réseau, incidents en cours, **charge par intervenant**, **santé de la collecte**, maintenances, équipements critiques |
| 3 | Technicien | `/console` | File de traitement, alertes temps réel, sites affectés, équipements HS, actions en cours |
| 4 | *(transverse)* | `/equipements/:id` | Équipement : CPU, RAM, trafic, latence, pertes, disponibilité, historique, identifiants par outil |
| — | Agent terrain | `/terrain` | Tournée, changement d'état, compte rendu avec relevé GPS, signalement de panne |

Le **drill-down** fonctionne dans les deux sens : KPI global → ministère →
site → équipement → incident, et retour. Tout nom cliquable mène quelque
part.

---

## 4. Les KPI, et d'où ils viennent

| Famille | Indicateurs | Source |
|---|---|---|
| **Réseau** | disponibilité globale / par site / par ministère, perte de paquets, latence, bande passante, équipements indisponibles | hypertable `metric_value`, agrégat continu `metric_hourly` |
| **Incidents** | total, ouverts, résolus, critiques, en retard, taux de résolution, MTTA, MTTR, récurrents | vue `v_incident` (sévérité et statut normalisés en SQL) |
| **Supervision** | équipements totaux / supervisés, taux de couverture, sites non supervisés, alertes actives et critiques | `fact_supervision_coverage_daily`, `v_node` |
| **SLA** | conformité MTTA / MTTR par gravité, dépassements | `ops_sla_target` (objectifs modifiables depuis l'écran SLA) |

### Deux normalisations invisibles mais décisives

L'ETL stocke les sévérités **brutes**, telles que chaque outil les
renvoie : `5` pour Zabbix, `major` pour NSP, `2` pour Centreon, `1` pour
iTop. Un filtre `WHERE severity = 'critical'` écrit naïvement ne
renverrait donc que les incidents NSP. La traduction est faite en SQL par
`noc_norm_severity()` et `noc_norm_status()`
(`backend/sql/01_backend_extensions.sql`), pour que les filtres, les
`GROUP BY` et les index restent exécutés par PostgreSQL.

Aucun service du backend ne lit `fact_incident` ni `dim_node`
directement : tout passe par `v_incident` et `v_node`. Si le schéma de
l'ETL évolue, seul ce fichier SQL est à reprendre.

---

## 5. Arborescence

```
noc/
├── etl/                    Collecte (Celery) — écrit dans l'entrepôt
│   ├── extract/            connecteurs API + lecteurs de dumps, par outil
│   ├── transform/          normalisation, déduplication, causes, identités
│   ├── load/               chargement dimensions / faits / métriques
│   ├── pipelines/          tâches Celery, statut de collecte (Redis)
│   ├── scripts/            découverte géographique, restauration de dumps
│   └── sql/                DDL de l'entrepôt (dimensions, faits, TimescaleDB)
│
├── backend/                API FastAPI — lit l'entrepôt, écrit ops_*
│   ├── app/routes/         70 endpoints /api/*, dont /api/internal/*
│   ├── app/services/       KPI, incidents, métriques, veilleur, rapports
│   ├── sql/                extensions backend (vues, fonctions, tables ops_*)
│   └── scripts/            create_user.py · seed_demo.py
│
├── frontend/               Console React — 4 tableaux de bord + transverses
│   └── src/{api,lib,store,hooks,components,pages}
│
├── database/               Outils NetXMS (dump source) · legacy/ = obsolète
├── nginx/                  Passerelle TLS
└── docker-compose.yml      7 services par défaut, 11 outils sous profil « tools »
```

Documentation détaillée :

* **[backend/README.md](backend/README.md)** — schéma, veilleur d'incidents,
  normalisation, API, scripts d'exploitation
* **[frontend/README.md](frontend/README.md)** — parti pris visuel, profils,
  temps réel, cadences de rafraîchissement
* **[etl/README.md](etl/README.md)** — connecteurs, transformation, chargement

---

## 6. Exploitation courante

```bash
# État de la plateforme
curl -s http://localhost:8000/api/health | python -m json.tool

# Journaux
docker compose logs -f backend etl-worker

# Forcer une collecte immédiate
docker compose exec etl-worker python -c \
  "from etl.pipelines.tasks import collect_all_tools; collect_all_tools()"

# Vider le cache KPI (après un import massif ou une correction)
docker compose exec redis redis-cli --scan --pattern 'noc:*' | \
  xargs -r docker compose exec -T redis redis-cli del

# Gestion des comptes
docker compose exec backend python scripts/create_user.py --list
docker compose exec backend python scripts/create_user.py -u untel --reset-password
```

### Diagnostic

| Symptôme | Cause probable | Vérification |
|---|---|---|
| Tous les écrans sont vides | l'entrepôt n'a pas de données | écran **Collecte ETL** : si les six outils sont « jamais collecté », aucun `*_API_URL` n'est renseigné |
| Les chiffres sont figés | un connecteur est arrêté | même écran : la colonne « Dernière collecte » est la seule qui le révèle — un total d'équipements reste rassurant même vieux de trois jours |
| Beaucoup d'équipements « muets » | la collecte de métriques s'est arrêtée | `/equipements?state=silent` |
| Le flux temps réel affiche « coupé » | WebSocket non relayé | vérifier `proxy_set_header Upgrade` dans le nginx en amont |
| Déconnexion toutes les 30 min | `REFRESH_COOKIE_SECURE=true` sur une origine `http://` | passer à `false` en local, ou servir en HTTPS |
| `500` sur toutes les routes métier | `01_backend_extensions.sql` non appliqué | les journaux du backend le disent au démarrage ; `/api/health` renvoie `database: degraded` |

---

## 7. Vérification de bout en bout

La pile a été exécutée entièrement sous Docker et vérifiée à quatre
niveaux. Les scripts sont reproductibles.

| Suite | Ce qu'elle couvre | Résultat |
|---|---|---|
| **API** — 73 contrôles | les 70 endpoints, la normalisation des 6 vocabulaires de sévérité, le filtrage multi-outils, l'export CSV (BOM UTF-8), la boucle complète acquitter → affecter → escalader → commenter → résoudre avec calcul du MTTR, la création de compte, le RBAC (agent terrain refusé sur `/api/incidents`, technicien refusé sur l'affectation), les rapports PDF et DOCX | 73/73 |
| **WebSocket** — 6 contrôles | poignée de main à travers nginx, authentification par première trame, battement de cœur, diffusion d'un incident en direct, refus d'un jeton invalide et d'une trame non conforme | 6/6 |
| **Veilleur** — 4 contrôles | un `INSERT` SQL brut dans `fact_incident` (exactement ce que fait l'ETL, sévérité `'5'` de Zabbix, aucun appel HTTP) est découvert seul par le backend, diffusé **déjà normalisé** en `critical`, et marqué dans `ops_incident_notified` | 4/4 |
| **Interface** — 19 contrôles | rendu réel dans un navigateur : les 13 écrans, la connexion, la redirection par rôle et le contenu effectif de chaque accueil (détection d'écran blanc) | 19/19 |

Vérifié également : schéma appliqué à l'initialisation (TimescaleDB 2.17.2,
20 tables, vues `v_node`/`v_incident`, hypertable, fonctions de
normalisation), redémarrage complet de la pile, chaîne ETL → Redis →
`/api/interop/status`, service worker non mis en cache, et repli SPA sur
les liens profonds.

**Non couvert** : les six outils de supervision réels ne sont pas
joignables depuis cette machine. Le comportement vérifié est celui de la
dégradation — un connecteur en échec est isolé, les autres poursuivent, et
l'écran « Collecte ETL » affiche `error` / `ok` / `not_configured` par
outil.

---

## 8. Sécurité

* Rôles vérifiés **côté serveur** sur chaque route sensible
  (`app/dependencies/auth.py`). Le RBAC du frontend n'est que du confort
  d'interface.
* Le rôle est relu en base à chaque requête, jamais pris dans le seul
  JWT : un compte rétrogradé en cours de session voit son jeton refusé.
* Jeton d'accès **en mémoire uniquement**, rafraîchissement par cookie
  httpOnly inaccessible à JavaScript.
* Connexion par PIN réservée aux agents terrain — jamais aux comptes
  directeur ou chef NOC, qui portent trop de privilèges pour un facteur à
  quatre chiffres. Verrouillage par IP après échecs répétés.
* Routes `/api/internal/*` protégées par une clé statique partagée avec
  l'ETL ; sans `INTERNAL_API_KEY`, elles répondent 503 plutôt que de
  s'ouvrir.
* Un compte est **désactivé, jamais supprimé** : supprimer une ligne de
  `dim_user` emporterait la traçabilité « qui a résolu cet incident ».
* HTTPS obligatoire en production. Le certificat auto-signé fourni
  (`nginx/generate_cert.sh`) est réservé au développement.

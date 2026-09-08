# Backend NOC RESINA — version 2

Backend réécrit pour l'ETL reconstruit (Zabbix, iTop, NetXMS, Centreon,
Nagios, Nokia NSP). L'ancien backend n'a pas été adapté : il a été
remplacé, parce qu'il reposait sur un schéma de base et un mode
d'alimentation qui n'existent plus.

---

## 1. Démarrage rapide

```bash
# 1. Schéma : les trois DDL de l'ETL, PUIS l'extension backend.
#    L'ordre compte, l'extension référence les tables de l'ETL.
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_dimensions.sql
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_facts.sql
psql "$NOC_WAREHOUSE_DSN" -f etl/sql/schema_timescale.sql
psql "$NOC_WAREHOUSE_DSN" -f backend/sql/01_backend_extensions.sql

# 2. Configuration
cp backend/.env.example backend/.env   # renseigner SECRET_KEY et INTERNAL_API_KEY

# 3. Lancement
pip install -r backend/requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. Vérification
curl http://localhost:8000/api/health
```

Créer le premier compte (aucun n'existe au départ) :

```sql
-- Mot de passe à générer :
--   python -c "import bcrypt;print(bcrypt.hashpw(b'VotreMotDePasse',bcrypt.gensalt()).decode())"
INSERT INTO dim_user (username, full_name, role, password_hash, is_active)
VALUES ('directeur', 'Nom Prénom', 'directeur', '<hash bcrypt>', true);
```

---

## 2. Pourquoi l'ancien backend ne pouvait pas fonctionner

| Sujet | Ancien backend | Nouvel ETL | Conséquence |
|---|---|---|---|
| Base | `noc_db` séparée | entrepôt `NOC_WAREHOUSE_DSN` | deux bases distinctes, aucune donnée commune |
| Alimentation | `POST /api/incidents/ingest` | écriture directe dans `fact_incident` | l'endpoint n'était plus jamais appelé |
| Cause d'incident | `cause_id` → FK `dim_cause` | `cause_category` texte libre | jointure impossible |
| Métriques | table `fact_metric` | hypertable `metric_value` | table inexistante |
| Géographie | `dim_province`, `dim_organisation` | `dim_ministry`, FK nullables | tables inexistantes, contraintes NOT NULL invalides |
| Parc | `dim_asset` + synchro iTop | `fact_supervision_coverage_daily` | table inexistante |
| Statut ETL | clé Redis `noc:collector:status` | clés `noc:etl:status:<outil>` | page Interopérabilité vide |
| KPI mensuels | vue matérialisée `mv_kpi_node_monthly` | — | vue inexistante |

Deux écarts supplémentaires, moins visibles mais plus dangereux, ont été
découverts en lisant les connecteurs :

**La sévérité n'est pas normalisée par l'ETL.**
`etl/transform/normalize_incidents.py` recopie la valeur brute de chaque
outil. `fact_incident.severity` contient donc simultanément :

| Outil | Valeurs | Signification |
|---|---|---|
| Zabbix | `0`–`5` | 5 = désastre |
| NetXMS | `0`–`4` | 4 = critique |
| Centreon / Nagios | `0`–`3` | 2 = CRITICAL, 3 = UNKNOWN |
| iTop | `1`–`4` | priorité, 1 = la plus forte |
| Nokia NSP | `critical`, `major`, `minor`… | vocabulaire X.733 |

Un filtre `WHERE severity = 'critical'` écrit naïvement ne renvoie donc
que les incidents NSP, et le tableau de bord affiche des sévérités
incohérentes selon l'outil d'origine.

**Le statut non plus.** iTop renvoie `new`, `assigned`, `pending`,
`closed` là où les outils de supervision renvoient `open` / `resolved`.

Enfin, `dim_node` n'a **pas** de colonne `code` et `node_type` n'est
jamais renseigné par `etl/load/load_dimensions.py` (l'INSERT ne les
liste pas), alors que le frontend manipule un `node_code` partout.

---

## 3. Principe d'architecture retenu

> **Le backend ne modifie jamais un objet appartenant à l'ETL.**

Ce qui appartient à l'ETL : tout ce qui commence par `dim_`, `fact_`,
`metric_`. Ce qui appartient au backend : tout ce qui commence par
`ops_`, plus les vues `v_*` et les fonctions `noc_*`.

`sql/01_backend_extensions.sql` est **strictement additif et
idempotent** : ré-exécuter les DDL de l'ETL ne casse rien, et
ré-exécuter l'extension backend non plus.

### La traduction se fait en SQL, pas en Python

Deux fonctions et deux vues concentrent tout l'écart de schéma :

```sql
noc_norm_severity(source_tool, severity)  -- '5'/'major'/'2' -> critical|high|medium|low|info
noc_norm_status(source_tool, status)      -- 'assigned' -> acknowledged
v_node                                     -- code = nom, géographie aplatie, outils agrégés
v_incident                                 -- incident normalisé + contexte + is_maintenance
```

Le choix du SQL plutôt que de Python est délibéré : traduire en Python
imposerait de charger toutes les lignes en mémoire avant de pouvoir
filtrer ou grouper dessus. Ici, `WHERE severity = 'critical'` et
`GROUP BY severity` restent exécutés par PostgreSQL.

**Aucun service du backend ne lit `fact_incident` ou `dim_node`
directement** — tous passent par `v_incident` et `v_node`. Si le schéma
de l'ETL évolue, seul `sql/01_backend_extensions.sql` est à reprendre.

Si l'ETL normalise un jour la sévérité lui-même, les fonctions
deviennent des passe-plats (`'critical'` → `'critical'`) sans rien
casser.

---

## 4. Le veilleur d'incidents

C'est le changement fonctionnel principal.

Avant, l'ETL appelait `POST /api/incidents/ingest`, et c'est cet appel
qui déclenchait la diffusion WebSocket, les SMS et le push navigateur.
Le nouvel ETL n'appelle plus le backend. **Sans remplacement, plus
aucune alerte ne serait émise** — le dashboard n'afficherait les
incidents qu'au rafraîchissement de la page.

`app/services/watcher_service.py` interroge l'entrepôt toutes les 30
secondes et joue ce rôle. Il démarre avec l'application.

Deux points de conception :

- **Polling plutôt que `LISTEN/NOTIFY`.** La notification temps réel de
  PostgreSQL exigerait un TRIGGER sur `fact_incident`, donc une
  modification d'un objet de l'ETL. 30 secondes reste très en dessous de
  l'intervalle de collecte (300 s) : le veilleur n'est jamais le maillon
  lent.
- **Idempotence via `ops_incident_notified`.** Sans cette table, chaque
  passage re-notifierait tous les incidents critiques encore ouverts,
  soit un SMS toutes les 30 secondes par incident.

⚠️ **Un seul worker uvicorn**, sinon chacun lance son veilleur et les
alertes partent en double. Pour monter en charge : plusieurs workers avec
`WATCHER_ENABLED=false`, et un conteneur dédié au veilleur.

---

## 5. Ce que le backend écrit dans les tables de l'ETL

Trois exceptions à la règle de lecture seule, toutes sans risque de
collision :

1. **Incidents manuels** — `source_tool='manual'`, une valeur qu'aucun
   connecteur ne produit. La contrainte `UNIQUE (source_tool,
   external_id)` les isole complètement.
2. **Acquittement / résolution** — pose `acknowledged_at`,
   `resolved_at`, `status`. L'UPSERT de l'ETL les préserve : il applique
   `COALESCE` sur ces colonnes plutôt que de les écraser (voir
   `etl/load/load_facts.py::load_incidents`).
3. **`dim_user`** — créée par l'ETL, peuplée uniquement par le backend.

**L'assignation et l'escalade ne sont PAS écrites dans
`fact_incident`** : elles vivent dans `ops_incident_assignment`. Une
colonne `assigned_to_user_id` posée sur `fact_incident` survivrait
jusqu'au prochain cycle de collecte, puis serait silencieusement perdue
par l'UPSERT.

---

## 6. Intégration ETL → backend — FAIT

`etl/report_trigger.py` portait un TODO ; il est désormais implémenté et
appelle `POST /api/internal/reports/monthly` avec un repli propre :

* si `BACKEND_INTERNAL_URL` ou `INTERNAL_API_KEY` manquent, la fonction
  journalise et retourne `{"triggered": false, ...}` — elle ne lève pas ;
* si le backend est injoignable ou refuse, idem.

C'est délibéré : la collecte est le service critique, le rapport est un
livrable mensuel régénérable à la main depuis l'écran **Rapports**. Un
backend indisponible ne doit jamais faire échouer une tâche Celery de
collecte.

Le mois généré est celui **précédant** `as_of` : la tâche tourne le 1er à
02:30, donc le mois à clôturer est celui qui vient de s'achever. Cette
convention est portée par le backend, pas par l'ETL, pour qu'un appel
manuel donne le même résultat.

Les deux variables sont déjà câblées dans `docker-compose.yml` (service
`etl-worker`). Hors Docker, ajouter à `etl/.env` :

```bash
BACKEND_INTERNAL_URL=http://backend:8000
INTERNAL_API_KEY=<la même valeur que dans backend/.env>
```

Trois autres routes internes sont disponibles si l'ETL veut s'en servir :

| Route | Usage |
|---|---|
| `POST /api/internal/watcher/run` | déclenche la diffusion tout de suite après un chargement, sans attendre le passage périodique |
| `POST /api/internal/cache/invalidate` | vide le cache KPI après un import massif ou une correction |
| `POST /api/internal/maintenance-windows` | import des maintenances planifiées (aucun connecteur ne les collecte encore) |

---

## 7. API

Les URL attendues par le frontend existant sont conservées à
l'identique — `frontend/src/api/*.js` fonctionne sans modification.

**Routes supprimées** (l'ETL écrit directement en base) :
`POST /api/incidents/ingest`, `/ingest/bulk`, `POST /api/metrics/ingest`,
`POST /api/assets/sync/bulk`.

**Routes ajoutées** :

| Route | Apport |
|---|---|
| `GET /api/kpi/ministries` | dimension `dim_ministry`, absente de l'ancien schéma |
| `GET /api/metrics/nodes/{id}/series` | séries TimescaleDB, brutes < 48 h puis agrégat horaire |
| `GET /api/metrics/nodes/{id}/latest` | dernière valeur de chaque métrique |
| `GET /api/assets/coverage/trend` | évolution de la couverture |
| `GET /api/sla/targets`, `PATCH /api/sla/targets/{severity}` | objectifs SLA configurables |
| `GET /api/incidents/{id}`, `/timeline`, `POST .../assign`, `/escalate`, `/comment` | flux de traitement complet |
| `GET /api/alerts/counts` | compteurs par sévérité |
| `/api/internal/*` | intégration ETL |

`GET /api/assets/coverage` garde son préfixe `/api/assets` pour ne pas
casser `frontend/src/api/assets.js`, bien que `dim_asset` n'existe plus.

---

## 8. Points d'attention connus

**Le taux de couverture vaudra 100 %.** `dim_node` n'est peuplée que par
ce que les outils remontent, donc « équipements totaux » et « équipements
supervisés » sont aujourd'hui le même ensemble. Le chiffre ne deviendra
significatif que le jour où un inventaire théorique complet (CMDB iTop)
alimentera `dim_node`. La réponse le signale explicitement via
`is_complete_inventory: false`.

**La disponibilité a deux modes de calcul.** Si les outils publient la
métrique `availability_pct`, c'est elle qui est utilisée. Sinon, elle est
déduite des temps d'indisponibilité :
`100 − (Σ downtime / (nb équipements × durée))`. C'est une approximation,
qui restera en usage tant que `NAGIOS_MODE` et `NSP_FM_MODE` ne sont pas
arrêtés côté agence.

**La géographie peut être vide.** `dim_ministry`, `dim_region` et
`dim_locality` ne sont peuplées que par
`etl/scripts/discover_geography.py`. Tant qu'il n'a pas tourné, les
nœuds n'ont ni site ni ministère : `GET /api/kpi/ministries` renvoie une
liste vide et la carte n'affiche rien. Ce n'est pas une erreur, et tous
les agrégats du backend tolèrent ces valeurs nulles.

**`node_code` est le nom de l'équipement.** `dim_node` n'ayant pas de
colonne `code`, `v_node` expose `name` comme `code`. Les filtres par
`node_code` font une recherche partielle insensible à la casse.

**Les libellés de cause doivent suivre l'ETL.** `dim_cause` est peuplée
par l'extension SQL avec les neuf catégories de
`etl/transform/causes.py`. Toute nouvelle règle regex ajoutée là-bas doit
recevoir sa ligne ici, sinon la cause s'affichera sans libellé.

---

## 9. Tests

`tests/test_integration.py` monte un jeu de données reproduisant ce que
l'ETL écrit réellement — sévérités brutes des six outils, statuts iTop,
nœuds sans site, sites sans coordonnées, métriques TimescaleDB — puis
exerce l'ensemble des endpoints.

```bash
createdb noc_warehouse
psql noc_warehouse -f ../etl/sql/schema_dimensions.sql
psql noc_warehouse -f ../etl/sql/schema_facts.sql
psql noc_warehouse -f ../etl/sql/schema_timescale.sql
psql noc_warehouse -f sql/01_backend_extensions.sql

NOC_WAREHOUSE_DSN=postgresql://noc:noc@localhost:5432/noc_warehouse \
PYTHONPATH=. python3 tests/test_integration.py
```

Couvre notamment : la normalisation des six vocabulaires de sévérité, les
filtres SQL sur valeurs hétérogènes, le contrôle d'accès par rôle, la
neutralisation des KPI par fenêtre de maintenance, l'idempotence du
veilleur, et la génération PDF/DOCX.

---

## 10. Complément v2.1 — ce qu'a apporté la refonte du frontend

La refonte de l'interface a fait apparaître trois manques dans l'API. Ils
sont comblés par des routes **additives** : aucune route existante n'a
changé de forme.

### 10.1 Inventaire des équipements — `/api/nodes`

Il n'existait aucun moyen de parcourir le parc. `/api/kpi/nodes` répond à
« les 10 équipements les plus incidentés du mois » ; il ne répond pas à
« montre-moi l'équipement X maintenant », qui est la question la plus
fréquente en salle. Sans cette route, le niveau 4 de l'architecture
métier (« Équipement | CPU | RAM | trafic | latence | pertes ») était
inatteignable.

| Route | Apport |
|---|---|
| `GET /api/nodes` | parcours paginé et filtrable (nom/IP, site, région, ministère, type, outil, état), avec dernières mesures et incidents ouverts |
| `GET /api/nodes/states` | répartition du parc par état — l'en-tête des vues parc |
| `GET /api/nodes/{id}` | fiche complète : identité, identifiants par outil, métriques disponibles, MTTR 90 j, indisponibilité 30 j |
| `GET /api/nodes/{id}/incidents` | historique d'incidents de l'équipement |

**L'état d'un équipement est DÉDUIT, pas lu.** L'ETL ne publie aucun champ
up/down. `services/node_service.py` le calcule en SQL, dans cet ordre :

| État | Règle |
|---|---|
| `maintenance` | une fenêtre `ops_maintenance_window` active le couvre |
| `down` | incident critique/majeur ouvert de cause `equipement_down`, `lien_down` ou `alimentation`, **ou** dernière `availability_pct` nulle |
| `degraded` | au moins un incident ouvert, ou seuil dépassé (dispo < 99 %, pertes > 5 %, CPU/RAM > 90 %) |
| `silent` | aucune métrique reçue depuis 6 h |
| `up` | le reste |

L'état `silent` mérite une attention particulière : il ne veut pas dire
« en panne », il veut dire **« on ne sait plus »**. C'est l'angle mort que
les tableaux de bord génériques comptent comme « OK », et c'est pourquoi
il apparaît comme un compteur distinct dans l'interface.

Le calcul est en SQL et non en Python pour que le tri « les plus dégradés
d'abord » porte sur **tout** le parc et pas seulement sur la page
affichée : un tri côté client sur 50 lignes sorties d'un ordre
alphabétique ne remonterait jamais l'équipement en panne de la page 7.

### 10.2 Référentiel — `/api/geo`

Les listes déroulantes de filtre (ministère / région / site / type / outil)
n'avaient aucune source. Le frontend aurait dû les coder en dur, ce qui
casse dès que l'ETL découvre une nouvelle localité.

| Route | Apport |
|---|---|
| `GET /api/geo/reference` | tout le référentiel en un appel, avec cache Redis de 10 min |
| `GET /api/geo/regions` · `/localities` · `/ministries` | listes unitaires |

### 10.3 Lectures agrégées

| Route | Pourquoi |
|---|---|
| `GET /api/metrics/network/series` | courbe d'une métrique agrégée sur le parc. Sans elle, tracer « la latence du réseau » demandait une requête par nœud puis une moyenne côté navigateur. Renvoie aussi `min`, `max` et `nb_nodes` : une moyenne à 40 ms peut recouvrir 290 sites à 15 ms et 10 sites à 800 ms |
| `GET /api/metrics/top` | classement des équipements sur une métrique. Le sens du tri suit la métrique (pire latence en tête, plus mauvaise disponibilité en tête) |
| `GET /api/alerts/summary` | le bandeau d'état permanent en un appel : compteurs par gravité, non acquittés, non affectés, escaladés, > 24 h, et **ancienneté du plus ancien non acquitté** — le véritable indicateur de tension d'un NOC |
| `GET /api/incidents/workload` | charge par intervenant, avec la ligne « non affecté » conservée en tête : c'est l'information la plus utile du tableau |
| `GET /api/incidents/export.csv` | export du résultat courant du filtre, séparateur `;` et BOM UTF-8 (destination réelle : Excel francophone) |

Total : **70 chemins `/api/*`** (74 opérations HTTP), plus le flux WebSocket `/ws/alerts`.

---

## 11. Outils d'exploitation (`scripts/`)

### 11.1 Créer le premier compte — `scripts/create_user.py`

`POST /api/users` exige d'être déjà connecté en directeur ou chef NOC. Au
premier démarrage aucun compte n'existe : personne ne peut se connecter,
donc personne ne peut créer de compte. Ce script casse la boucle.

```bash
cd backend

# Un compte par rôle, pour parcourir les quatre tableaux de bord
python scripts/create_user.py --demo-set --password "MotDePasse123"
#   directeur / chefnoc / technicien / terrain

# Un compte précis
python scripts/create_user.py -u k.ouedraogo -r chef_noc \
    -n "Karim Ouedraogo" --password "MotDePasse123"

# Mot de passe oublié du seul directeur
python scripts/create_user.py -u directeur --reset-password

# Inventaire des comptes
python scripts/create_user.py --list
```

Ensuite, tout se fait depuis l'écran **Utilisateurs** de l'interface.

### 11.2 Données de démonstration — `scripts/seed_demo.py`

Tant que les six connecteurs ne pointent pas vers les vrais outils,
l'entrepôt est vide et tous les écrans affichent « aucune donnée » :
impossible de valider une maquette ou de former un exploitant.

```bash
cd backend
python scripts/seed_demo.py                    # 60 équipements, 180 jours
python scripts/seed_demo.py --nodes 150 --days 365
python scripts/seed_demo.py --purge            # n'efface QUE ses propres données
```

Le script respecte volontairement les contraintes de la production :

* les sévérités et statuts sont écrits **bruts**, dans le vocabulaire de
  chaque outil (`5` pour Zabbix, `major` pour NSP, `2` pour Centreon,
  `assigned` pour iTop), exactement comme
  `etl/transform/normalize_incidents.py` les recopie. Semer des valeurs
  déjà normalisées donnerait une démo qui marche et une production qui ne
  marche pas ;
* `source_tool` n'est jamais `manual` : cette valeur est réservée aux
  signalements humains ;
* tout ce qu'il écrit porte le préfixe `demo-`, donc `--purge` ne touche
  jamais une donnée réellement collectée.

Après un semis, videz le cache KPI pour voir les chiffres immédiatement :

```bash
redis-cli --scan --pattern 'noc:*' | xargs -r redis-cli del
```

---

## 12. Arborescence

```
backend/
├── sql/01_backend_extensions.sql   # additif, idempotent — À APPLIQUER
├── scripts/
│   ├── create_user.py              # ⭐ amorçage du premier compte
│   └── seed_demo.py                # ⭐ jeu de données de démonstration
├── app/
│   ├── main.py                     # + veilleur, + vérification du schéma
│   ├── core/                       # config, sécurité, sessions, débit
│   ├── db/                         # session SQLAlchemy, client Redis
│   ├── dependencies/auth.py        # rôles, clé interne ETL
│   ├── models/
│   │   ├── warehouse.py            # tables ETL (lecture seule)
│   │   └── operations.py           # dim_user + tables ops_*
│   ├── schemas/                    # contrats Pydantic
│   ├── services/
│   │   ├── watcher_service.py      # ⭐ remplace l'ingestion webhook
│   │   ├── node_service.py         # ⭐ inventaire + état dérivé
│   │   ├── geo_service.py          # ⭐ référentiel des filtres
│   │   ├── kpi_service.py          # agrégats sur v_incident
│   │   ├── interop_service.py      # clés Redis de l'ETL
│   │   ├── coverage_service.py     # remplace asset_service
│   │   ├── metrics_service.py      # metric_value / metric_hourly
│   │   └── …
│   └── routes/                     # 70 endpoints /api/*, dont /api/internal/*
├── tests/test_integration.py
├── Dockerfile
├── requirements.txt
└── .env.example
```

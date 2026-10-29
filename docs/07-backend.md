# 7. Backend (API)

## Technologies

| Besoin | Bibliothèque |
|---|---|
| API REST et WebSocket | FastAPI, servi par Uvicorn (2 processus) |
| Base PostgreSQL | SQLAlchemy 2 + psycopg2 |
| Instantané, cache, sessions, temps réel | redis (client asynchrone) |
| Appels vers les outils sources | httpx (asynchrone) ; psycopg 3 pour NetXMS par la base (collecteur) |
| Validation des entrées/sorties | Pydantic 2 |
| Sécurité | bcrypt, PyJWT |
| Rapports | fpdf2 (PDF), python-docx (DOCX) |
| Notifications | smtplib (courriel), twilio (SMS), pywebpush (navigateur) |

## Structure de `backend/app/`

| Dossier | Contenu |
|---|---|
| `main.py` | Démarrage : refuse de démarrer si `SECRET_KEY` fait moins de 32 caractères ; vérifie le schéma **sans bloquer** (les écrans temps réel fonctionnent même sans base) ; lance l'abonnement au canal Redis des nouvelles alertes. |
| `core/config.py` | Toutes les variables d'environnement du backend, commentées. |
| `core/session_store.py` | Sessions de connexion, révocation des jetons d'accès, verrouillage après échecs (mot de passe et PIN), dans Redis. |
| `dependencies/auth.py` | `get_current_user` (jeton + rôle relu en base) et `require_role(...)`. |
| `models/operations.py` | Les tables PostgreSQL, en SQLAlchemy. Miroir de `sql/schema.sql`. |
| `schemas/` | Formats d'entrée et de sortie (comptes, authentification, notifications). |
| `routes/` | Points d'entrée, regroupés par **nature d'accès** (voir ci-dessous). |
| `services/` | Logique métier. Les routes sont minces ; le travail est ici. |

Les routes sont séparées selon ce qu'elles touchent :

- `live.py` — **lecture de l'instantané Redis** : rapide, sans écriture, sans
  appel sortant (sauf les courbes, qui interrogent l'outil source) ;
- `territory.py` — **périmètre territorial et incidents iTop** : découpage
  région → province → site, incidents, SLA et indicateurs d'incidents (ces
  derniers interrogent iTop, avec cache) ;
- `operations.py` — maintenances et interventions (lues dans l'instantané),
  **objectifs SLA** (seule écriture métier en base) et agrégats journaliers ;
- `audit.py` — lecture du journal d'audit ;
- les autres (`auth`, `users`, `notifications`, `report`, `ws`, `health`) ont
  chacune une contrainte propre.

## Les routes

Toutes sont préfixées par `/api`, sauf le WebSocket. La documentation
interactive (Swagger) est générée sur `/docs` lorsque `API_DOCS_ENABLED=true` ;
elle est fermée par défaut.

### Authentification et comptes

| Méthode | Route | Rôle requis | Rôle |
|---|---|---|---|
| POST | `/auth/login` | — | Connexion par identifiant et mot de passe |
| POST | `/auth/pin-login` | — (agent terrain) | Connexion par PIN |
| POST | `/auth/refresh` | cookie | Renouveler le jeton d'accès |
| POST | `/auth/logout` | — | Déconnexion |
| GET / PATCH | `/auth/me` | connecté | Lire / modifier ses identifiants (sans le rôle) |
| PATCH | `/auth/me/password` | connecté | Changer son mot de passe |
| POST | `/auth/users/{id}/revoke-sessions` | chef NOC | Couper les sessions d'un compte |
| GET | `/users` | connecté | Liste des comptes (sert aussi aux sélecteurs d'affectation) |
| POST | `/users` | chef NOC | Créer un compte |
| PATCH | `/users/{id}` | chef NOC | Modifier un compte, son rôle |
| POST | `/users/{id}/deactivate` | chef NOC | Désactiver |
| POST | `/users/{id}/reset-password` | chef NOC | Mot de passe provisoire |
| POST | `/users/{id}/reset-pin` | chef NOC | Définir le PIN |

### État courant (instantané Redis)

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/overview` | Tuiles de synthèse : parc, alertes, sites touchés |
| GET | `/sites` | Synthèse par site |
| GET | `/alerts` | Alertes actives (filtres : `severity`, `tool`, `kind`, `site`, `acknowledged`, `include_maintenance`, `search`, `limit`) |
| GET | `/alerts/{clé}` | Détail d'une alerte : contexte de l'outil (tags, donnée opérationnelle, commentaires…), équipement concerné |
| GET | `/alerts/by-severity`, `/alerts/by-tool`, `/alerts/ages`, `/alerts/hour-distribution` | Répartitions |
| GET | `/nodes` | Équipements (filtres : `state`, `site`, `tool`, `search`, `sort`, `limit`, `offset`) |
| GET | `/nodes/{id}` | Fiche d'un équipement : sources, état chez chaque outil, faits de fiche (`details` : inventaire, interfaces, disponibilité de l'agence), panne en cours, dernier démarrage, maintenances et interventions |
| GET | `/nodes/{id}/metrics` | Courbe d'un équipement — **interroge l'outil source** |
| GET | `/nodes/{id}/metrics-latest` | Dernières mesures d'un équipement |
| GET | `/nodes/states`, `/nodes/coverage` | Comptes par état, couverture par outil |
| GET | `/network/snapshot`, `/network/down`, `/network/top` | Indicateurs réseau ; l'instantané donne aussi `links` (interfaces actives, liens surveillés, capacité) et `agency_availability` (disponibilité calculée par l'agence dans NetXMS) quand une source les publie |
| GET | `/network/series` | Courbe agrégée sur un échantillon d'équipements — **interroge les outils** |
| GET | `/interop/status`, `/interop/merge` | Santé de la collecte, rapport de fusion (dont équipements vus par un seul outil et échantillon des alertes sans équipement) |

Toutes les clés d'alerte (`netxms:5647364`) et d'équipement contiennent un
deux-points : elles doivent être encodées dans les URL.

### Exploitation

Le NOC ne crée, n'acquitte ni ne résout aucune alerte ni aucun incident :
toutes ses données viennent des API des outils. Il n'écrit en base que ses
paramètres (objectifs SLA), ses comptes et son journal d'audit.

| Méthode | Route | Rôle requis |
|---|---|---|
| GET | `/maintenance` | Maintenances planifiées (changements iTop, maintenances Zabbix) — lecture seule ; filtres `scope`, `region`, `province`, `site`, `search` |
| GET / PUT | `/sla/targets` | lecture : tous ; écriture : directeur, chef NOC |
| GET | `/geo/options`, `/geo/breakdown`, `/geo/sites/{site}` | Découpage territorial, ventilation par niveau, fiche d'un site |
| GET | `/incidents` | Tickets iTop ouverts du périmètre, avec leur SLA |
| GET | `/incidents/history` | Tickets iTop de la période, clos ou non, paginés ; ⚠️ interroge iTop |
| GET | `/incidents/{clé}` | Fiche d'incident : ticket, événement Zabbix d'origine, état de l'équipement chez chaque outil, alertes liées |
| GET | `/sla/incidents` | Respect des SLA par région, province, site ou équipement ; ⚠️ interroge iTop |
| GET | `/sla/contract` | Engagements contractuels (SLT) déclarés dans iTop, en minutes par gravité ; ⚠️ interroge iTop (cache 5 min) |
| GET | `/sla/at-risk` | Incidents iTop ouverts hors délai ou à moins de 25 % de leur délai de résolution ; filtres `region`, `province`, `site` |
| GET | `/kpi/incidents?days=` | Indicateurs des tickets iTop de la période : volumes, taux de résolution, équipements récurrents (≥ 3 tickets), causes (code de résolution iTop), part sans cause, réouverts, sites et organisations ; ⚠️ interroge iTop |
| GET | `/kpi/trend`, `/kpi/monthly`, `/kpi/sites` | tous |
| GET | `/organisations` | Disponibilité par organisation (ministère, structure) du périmètre |
| GET | `/interventions` | Ordres de travail iTop — lecture seule ; filtres `status`, `region`, `province`, `site`, `search` |
| GET | `/trend/live` | Historique court du périmètre (24 h, un point par cycle de collecte : disponibilité, équipements HS, alertes, incidents) — mini-courbes des tuiles |
| GET | `/search/suggest` | Suggestions des barres de recherche (`q`, `kinds`, `limit`), lues dans l'instantané |
| GET | `/report/monthly?month=&year=&format=pdf\|docx` | directeur, chef NOC — disponibilité et sites (`kpi_daily`), incidents, délais, causes et dépassements (tickets iTop du mois) |
| GET | `/history/nodes/{id}?days=` | Disponibilité d'un équipement et de ses liens sur la période, pannes, MTTR, MTBF, frise des états, alertes ; `available: false` si le journal n'existe pas |
| GET | `/history/ranking?kind=node\|link&days=&limit=` | Équipements ou liens les moins disponibles sur la période, dans le périmètre (`region`, `province`, `site`) |
| GET | `/history/status` | Profondeur du journal : depuis quand, combien d'équipements, de liens, d'alertes |
| GET | `/audit?action=&user_id=&limit=&offset=` | directeur, chef NOC — journal d'audit, du plus récent au plus ancien |

### Notifications, santé, temps réel

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/notifications/vapid-public-key` | Clé des notifications navigateur |
| POST / DELETE | `/notifications/subscribe` | Abonnement navigateur |
| GET | `/notifications/email/status` | Chaîne courriel (chef NOC) |
| POST | `/notifications/email/test` | Courriel de test (chef NOC) |
| GET | `/health` | Santé : Redis, collecteur, base ; outils sources en échec et file des notifications (informatif). Publique, 503 si une dépendance est en erreur |
| GET | `/health/live` | Le processus répond (utilisé par Docker) |
| WS | `/ws/alerts` | Flux des nouvelles alertes (authentification par première trame) |

## La base de données du NOC

Schéma : `backend/sql/schema.sql`. Il est **rejouable sans danger** sur une
base en service (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF
NOT EXISTS`) : c'est ainsi qu'on met à jour la base. Il est appliqué
automatiquement au premier démarrage d'un volume vide.

`schema.sql` est le chemin de migration faisant autorité : l'image ne lance
aucune migration. Les révisions Alembic de `backend/migrations/versions`
(jusqu'à `0004`, suppression des tables qui n'étaient plus alimentées)
existent pour qui préfère cet outil ; elles mènent au même schéma.
**Rejouer `schema.sql` supprime les tables `ops_alert_state`,
`ops_alert_timeline`, `ops_manual_incident`, `ops_maintenance_window` et
`ops_field_intervention`, avec leur contenu.** L'index unique d'expression de
`kpi_daily` représente le site global par `COALESCE(site, '')`, car la clé de
ce total contient volontairement `site=NULL`.

La base ne contient que ce que le NOC produit lui-même. Équipements,
alertes, incidents, maintenances et interventions vivent dans Redis
(instantané) et chez les outils sources.

| Table | Contenu |
|---|---|
| `noc_user` | Comptes : identifiant, nom, rôle, empreintes du mot de passe et du PIN, courriel, abonnement aux alertes, rattachement |
| `ops_sla_target` | Délais cibles TTA/TTR par gravité ; la disponibilité réseau n'est pas une cible SLA configurable |
| `ops_push_subscription` | Abonnements aux notifications navigateur |
| `ops_notification_log` | Journal des envois (courriel, SMS) |
| `ops_alert_notified` | Verrou anti-doublon des notifications |
| `ops_notification_retry` | Envois échoués en attente d'une nouvelle tentative (courriel, SMS), puis envoyés ou abandonnés |
| `ops_audit_log` | Journal d'audit : connexions (réussies et refusées), comptes créés, modifiés, désactivés, mots de passe et PIN fixés, sessions coupées, objectifs SLA modifiés — auteur, cible, détail (jamais de secret), adresse IP |
| `kpi_daily` | Bilan journalier par site (écrit par le collecteur, rattrapé depuis le journal) |
| `hist_state` | Journal : périodes d'état de chaque équipement et de chaque lien surveillé (écrit par le collecteur) |
| `hist_alert` | Journal : chaque alerte et chaque ticket iTop, de l'ouverture à la fermeture (écrit par le collecteur) |

## Développer sur le backend

La boucle la plus simple, sans rien installer :

```bash
# après une modification du code
docker compose up -d --build backend
docker compose logs -f backend
```

Pour exécuter un bout de code dans le contexte de l'application :

```bash
docker compose exec -T backend python - <<'PY'
from app.db.session import SessionLocal
from app.models import User
db = SessionLocal()
print([u.username for u in db.query(User).all()])
PY
```

Vérifier le style :

```bash
docker run --rm -v "$PWD:/src" -w /src/backend python:3.12-slim \
  sh -c "pip install -q ruff && ruff check app ../integrations ../collector"
```

Développer **hors Docker** (avec rechargement automatique) est possible mais
demande un peu de préparation : Redis n'est pas publié sur le poste, et le
backend importe `integrations/` et `collector/` depuis la racine. Il faut un
`docker-compose.override.yml` qui publie `6379` pour Redis, puis :

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv/Scripts/activate sous Windows
pip install -r requirements-dev.txt
export PYTHONPATH=..  NOC_DATABASE_URL=postgresql://noc:<mot de passe>@localhost:5436/noc \
       REDIS_URL=redis://localhost:6379/0  SECRET_KEY=<au moins 32 caractères>
uvicorn app.main:app --reload --port 8000
```

### Tests

Les tests de `backend/tests/` n'utilisent ni base ni Redis réels : sources et
instantané sont remplacés par des doublures (`tests/fakes.py` pour le
collecteur). Ils se lancent depuis `backend/`, dans l'environnement virtuel
ci-dessus (`requirements-dev.txt`) :

```bash
PYTHONPATH=.. python -m pytest -q tests      # PYTHONPATH="..;." sous Windows
```

`test_integration.py` est à part : il écrit dans une base et refuse de
s'exécuter sans `NOC_TEST_DATABASE_URL` vers une base dédiée (`*_test`).

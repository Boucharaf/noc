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
- `operations.py` — **écriture dans PostgreSQL** : acquittements, maintenances,
  SLA, et lecture des agrégats journaliers ;
- les autres (`auth`, `users`, `field`, `notifications`, `report`, `ws`,
  `health`) ont chacune une contrainte propre.

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
| GET | `/alerts` | Alertes actives (filtres : `severity`, `tool`, `site`, `acknowledged`, `include_maintenance`, `limit`) |
| GET | `/alerts/{clé}` | Détail d'une alerte et son journal d'actions |
| GET | `/alerts/by-severity`, `/alerts/by-tool`, `/alerts/hour-distribution` | Répartitions |
| GET | `/nodes` | Équipements (filtres : `state`, `site`, `tool`, `search`, `sort`, `limit`, `offset`) |
| GET | `/nodes/{id}` | Fiche d'un équipement |
| GET | `/nodes/{id}/metrics` | Courbe d'un équipement — **interroge l'outil source** |
| GET | `/nodes/states`, `/nodes/coverage` | Comptes par état, couverture par outil |
| GET | `/network/snapshot`, `/network/down`, `/network/top` | Indicateurs réseau |
| GET | `/network/series` | Courbe agrégée sur un échantillon d'équipements — **interroge les outils** |
| GET | `/interop/status`, `/interop/merge` | Santé de la collecte, rapport de fusion |

Toutes les clés d'alerte (`netxms:5647364`) et d'équipement contiennent un
deux-points : elles doivent être encodées dans les URL.

### Exploitation (PostgreSQL)

| Méthode | Route | Rôle requis |
|---|---|---|
| POST | `/alerts/{clé}/acknowledge`, `/assign`, `/resolve` | directeur, chef NOC, technicien |
| POST | `/alerts/{clé}/note` | tous |
| POST | `/manual-incidents`, `/manual-incidents/{id}/resolve` | tous |
| GET / POST / DELETE | `/maintenance` | lecture : tous ; écriture : directeur, chef NOC |
| GET / PUT | `/sla/targets` | lecture : tous ; écriture : directeur, chef NOC |
| GET | `/sla/compliance`, `/sla/breaches`, `/sla/at-risk` | tous |
| GET | `/kpi/trend`, `/kpi/monthly`, `/kpi/sites`, `/kpi/causes`, `/kpi/resolution-times` | tous |
| GET / POST / PATCH | `/field/interventions` | création : directeur, chef NOC, technicien ; mise à jour : tous |
| GET | `/report/monthly?month=&year=&format=pdf\|docx` | directeur, chef NOC |

### Notifications, santé, temps réel

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/notifications/vapid-public-key` | Clé des notifications navigateur |
| POST / DELETE | `/notifications/subscribe` | Abonnement navigateur |
| GET | `/notifications/email/status` | Chaîne courriel (chef NOC) |
| POST | `/notifications/email/test` | Courriel de test (chef NOC) |
| GET | `/health` | Santé : Redis, collecteur, base |
| GET | `/health/live` | Le processus répond (utilisé par Docker) |
| WS | `/ws/alerts` | Flux des nouvelles alertes (authentification par première trame) |

## La base de données du NOC

Schéma : `backend/sql/schema.sql`. Il est **rejouable sans danger** sur une
base en service (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF
NOT EXISTS`) : c'est ainsi qu'on met à jour la base. Il est appliqué
automatiquement au premier démarrage d'un volume vide.

Les liens vers une alerte ou un équipement sont des **clés texte**
(`netxms:5647364`), sans clé étrangère : l'objet désigné vit dans Redis ou chez
l'outil source. Une note peut donc survivre à l'alerte qu'elle commente, et
c'est voulu.

| Table | Contenu |
|---|---|
| `noc_user` | Comptes : identifiant, nom, rôle, empreintes du mot de passe et du PIN, courriel, abonnement aux alertes, rattachement |
| `ops_alert_state` | Le travail du NOC sur une alerte : acquittement, affectation, escalade, cause, résolution. Une ligne seulement pour les alertes touchées. |
| `ops_alert_timeline` | Journal des actions sur les alertes (jamais écrasé) |
| `ops_manual_incident` | Incidents signalés à la main |
| `ops_maintenance_window` | Fenêtres de maintenance (sur un équipement ou un site) |
| `ops_sla_target` | Délais cibles et disponibilité par gravité |
| `ops_field_intervention` | Interventions terrain : statut, position, compte rendu |
| `ops_push_subscription` | Abonnements aux notifications navigateur |
| `ops_notification_log` | Journal des envois (courriel, SMS) |
| `ops_alert_notified` | Verrou anti-doublon des notifications |
| `ops_audit_log` | Journal d'audit |
| `kpi_daily` | Bilan journalier par site (écrit par le collecteur) |

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

> Les tests de `backend/tests/` visent l'ancienne architecture et ne
> fonctionnent plus (voir [chapitre 10](10-etat-du-projet.md)).

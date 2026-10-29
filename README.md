# Plateforme NOC RESINA

Tableau de bord du **centre de supervision (NOC)** du réseau de
l'administration burkinabè (RESINA, exploité par l'ANPTIC). La plateforme lit
les outils de supervision existants **par leurs API** — Zabbix, Centreon,
iTop, NetXMS, Nagios et Nokia NSP — et présente un écran par métier :
Directeur, Chef NOC, Technicien, Agent terrain. Elle ne recopie pas les
données des outils et n'en crée aucune : acquitter, affecter, résoudre se
fait dans l'outil source ou dans iTop. Elle tient seulement un **journal des
changements d'état** (équipements, liens, alertes) pour la disponibilité sur
la durée.

> **Ce fichier explique comment installer, lancer et mettre à jour le
> projet.** Pour **comprendre** le projet (métier, architecture, code,
> sécurité), lire la documentation : **[docs/README.md](docs/README.md)**.
> Une équipe qui **reprend** le projet commence par
> [docs/12-reprise-du-projet.md](docs/12-reprise-du-projet.md).

---

## Sommaire

1. [Prérequis](#1-prérequis)
2. [Installation et premier lancement](#2-installation-et-premier-lancement)
3. [Choisir ses sources de données](#3-choisir-ses-sources-de-données)
4. [Mettre à jour une installation existante](#4-mettre-à-jour-une-installation-existante)
5. [Tester les alertes par courriel](#5-tester-les-alertes-par-courriel)
6. [Commandes du quotidien](#6-commandes-du-quotidien)
7. [Configuration : les variables essentielles](#7-configuration--les-variables-essentielles)
8. [Adresses et ports](#8-adresses-et-ports)
9. [Problèmes fréquents](#9-problèmes-fréquents)
10. [Aller plus loin](#10-aller-plus-loin)

---

## 1. Prérequis

| Élément | Détail |
|---|---|
| **Docker** avec Compose v2 | Docker Desktop (Windows, macOS) ou Docker Engine (Linux). Toute la plateforme tourne en conteneurs : rien d'autre à installer pour la faire fonctionner. |
| **Mémoire allouée à Docker** | 4 Go pour la plateforme seule ; **8 Go** avec la base NetXMS et un ou deux outils de laboratoire ; 12 Go et plus avec Zabbix + iTop + Centreon. |
| **Disque** | 10 Go pour la plateforme ; +2 Go pour la base NetXMS restaurée ; +5 Go pour les outils de laboratoire. |
| **Git** | Pour récupérer le code. |
| **Un terminal bash** | Les commandes et scripts sont en bash. Sous Windows : **Git Bash** (installé avec Git). Sur une VM Ubuntu : le terminal par défaut. |
| **Ports libres** | 8443 et 8888 (interface) ; 5436 (base du NOC) ; en local, selon les outils lancés : 5438, 8025, 8081, 8082, 8084, 8085, 8086 (tous publiés sur 127.0.0.1 seulement). |

---

## 2. Installation et premier lancement

### Étape 1 — Récupérer le code

```bash
git clone https://github.com/Boucharaf/noc.git
cd noc
```

### Étape 2 — Créer le fichier de configuration

```bash
cp .env.example .env
```

Ouvrir `.env` et renseigner **au minimum** :

| Variable | Quoi mettre |
|---|---|
| `SECRET_KEY` | Une chaîne aléatoire d'au moins 32 caractères. Le backend **refuse de démarrer** sans elle. Générer : `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | Le mot de passe de la base du NOC. ⚠️ Il est figé à la création du volume : le changer ensuite rend la base inaccessible. |
| `REDIS_PASSWORD` | Le mot de passe de Redis (sessions, instantané). Obligatoire : `docker compose` refuse de démarrer sans lui. Générer avec la même commande que `SECRET_KEY`. |

`.env` contient des secrets : il est exclu de git et ne doit jamais y entrer.

### Étape 3 — Générer le certificat HTTPS

L'interface est servie en HTTPS par nginx, qui ne démarre pas sans
certificat. Le certificat n'est pas dans git : il faut le produire une fois.

```bash
bash nginx/generate_cert.sh
```

C'est un certificat **auto-signé** : le navigateur affichera un avertissement
à accepter. En production, le remplacer par un certificat de l'autorité de
l'agence (fichiers `nginx/certs/noc-selfsigned.crt` et `.key`).

### Étape 4 — Démarrer

Le **cœur** de la plateforme (collecteur, backend, interface, nginx, Redis,
PostgreSQL) démarre avec :

```bash
docker compose up -d --build
```

Le premier lancement construit les images (quelques minutes) et crée le
schéma de la base. Vérifier que tout est « healthy » :

```bash
docker compose ps
```

Les **outils locaux** (dump NetXMS, laboratoires, simulateur NSP, faux
serveur de courriel) ne démarrent pas avec le cœur : chacun a son **profil**
Docker Compose (§ 3). Pour les lancer à chaque `docker compose up` sans les
nommer, les lister une fois dans `.env` :

```ini
COMPOSE_PROFILES=netxms,nagios,nsp,mail
```

### Étape 5 — Créer le premier compte (Chef NOC)

Aucun compte n'existe au départ, et l'interface exige d'être connecté pour en
créer. Ce script crée le premier :

```bash
docker compose exec backend python scripts/create_user.py \
    -u chefnoc -r chef_noc -n "Chef NOC" -p "MotDePasse"
```

> Sous Windows, **passez toujours le mot de passe avec `-p`**. La saisie
> masquée (sans `-p`) peut enregistrer autre chose que ce qui a été tapé, et
> la connexion échoue ensuite avec « Identifiants invalides ».

### Étape 6 — Se connecter

Ouvrir **<https://localhost:8443>** et se connecter avec `chefnoc`.

Le Chef NOC crée ensuite **tous les autres comptes** depuis l'écran
*Utilisateurs* et leur attribue un rôle. Il est le seul à pouvoir le faire.
Chaque utilisateur modifie ensuite ses propres identifiants dans *Mon compte*.

| Rôle | Écran d'accueil |
|---|---|
| Directeur | Pilotage (disponibilité, SLA, tendances, rapports) |
| Chef NOC | Salle de supervision + gestion des comptes |
| Technicien | Console d'exploitation (suivi des alertes et incidents iTop) |
| Agent terrain | Tournée (interventions, ordres de travail iTop) |

À ce stade, **le tableau de bord est vide** : aucune source de données n'est
branchée. C'est normal — voir la section suivante.

---

## 3. Choisir ses sources de données

La plateforme ne stocke pas les équipements ni les alertes : elle les lit
chez les outils de supervision. Un outil s'active par la **seule présence de
son URL** dans `.env` (`<OUTIL>_API_URL`), et le mode d'accès se choisit par
la **forme** de cette URL : `https://…` (API, production), `postgresql://…`
(dump NetXMS, local), `file://…` (export Centreon, local).

| Situation | Données affichées | Mise en place |
|---|---|---|
| **A. Aucune source** | Aucune (écrans vides) | Rien à faire |
| **B. Dump NetXMS de production** | 1 409 équipements, 791 alarmes, 1 012 liens surveillés réels, **figés au 07/08/2026** | [§ 3.1](#31-base-netxms-restaurée-depuis-le-dump) |
| **B′. Export du journal Centreon** | 12 serveurs ANPTIC et leurs contrôles, **du 25/09 au 27/10/2026** | [§ 3.2](#32-export-du-journal-centreon) |
| **C. Outils de laboratoire** | Vrais Zabbix, iTop, Centreon et Nagios locaux, et un **simulateur NSP** | [§ 3.3](#33-outils-de-laboratoire) |
| **D. Outils réels de l'agence** | Le vrai réseau, en direct, par les API | [§ 3.4](#34-outils-réels-de-lagence) |

Les situations B, C et D se combinent : les équipements de plusieurs outils
sont fusionnés dans un même parc. **En production, seule la situation D
s'applique** : aucun dump, aucun export, aucun simulateur.

### Lancement local complet, en une fois

Pour un poste de développement avec toutes les sources locales (une fois le
dump restauré, § 3.1), dans `.env` :

```ini
COMPOSE_FILE=docker-compose.yml;docker-compose.dumps.yml
COMPOSE_PATH_SEPARATOR=;
COMPOSE_PROFILES=netxms,zabbix,nagios,nsp,mail
```

puis :

```bash
docker compose up -d --build
docker compose ps
```

| Profil | Ce qu'il lance | Mémoire |
|---|---|---|
| `netxms` | Base NetXMS restaurée depuis le dump (`netxms-db`) | ~0,5 Go |
| `zabbix` | Zabbix 7.0.23 de laboratoire (base, serveur, web, agent) | ~1 Go |
| `itop` | iTop 3.2.3 de laboratoire | ~1 Go |
| `centreon` | Centreon 22.10.7 de laboratoire | ~2 Go |
| `nagios` | Nagios Core 4.5.12 de laboratoire | ~0,2 Go |
| `nsp` | Simulateur Nokia NSP (`tools/nsp-sim`) | ~30 Mo |
| `netlab` | Six « équipements » de site simulés (SNMP, trafic, pannes) | ~60 Mo |
| `mail` | Mailpit, faux serveur de courriel | ~30 Mo |
| `tools` | Tous les outils de laboratoire à la fois | ~5 Go |
| `provision` | Tâche ponctuelle : déclarer les machines à superviser dans les laboratoires | — |

### 3.1 Base NetXMS restaurée depuis le dump

Le dump `database/netxmsbd07082026.sql` (ou sa version compressée
`database/netxmsbd07082026.sql.gz`) contient des données de production et est
**exclu de git**. Il doit être obtenu par un canal autorisé et copié à la main
dans `database/`. Le script de restauration attend le fichier SQL décompressé.

```bash
# 1. Démarrer la base NetXMS locale
docker compose --profile netxms up -d netxms-db

# 2. Dans .env, choisir le mot de passe du compte de lecture du NOC
#    NETXMS_DB_READER_PASSWORD=<un mot de passe>

# 3. Restaurer (≈ 4 min) : restauration, purge des secrets, compte de lecture
bash database/restore_netxms_dump.sh

# 4. Dans .env, brancher le collecteur sur cette base
#    NETXMS_API_URL=postgresql://netxms-db:5432/netxms
#    NETXMS_API_USER=noc_reader
#    NETXMS_API_PASSWORD=<le même mot de passe qu'à l'étape 2>

# 5. Prendre en compte la configuration
docker compose up -d collector backend
```

Les équipements apparaissent au cycle de collecte suivant (moins d'une
minute après le redémarrage du collecteur).

Sur une base **déjà restaurée** avant l'ajout de la fiche technique
(inventaire, interfaces, liens, disponibilité de l'agence), rejouer le script
de droits, sinon ces informations restent vides :

```bash
docker compose exec -T netxms-db psql -U netxms -d netxms \
  -v reader_password="$(grep -E '^NETXMS_DB_READER_PASSWORD=' .env | cut -d= -f2-)" \
  -f - < database/netxms_readonly_role.sql
```

### 3.2 Export du journal Centreon

`database/alertes.sql` est un export tabulé de la table `logs` de Centreon
(`centreon_storage`), fourni par l'agence. Malgré son extension, ce n'est pas
un dump SQL : il n'y a pas de base à restaurer. Le connecteur
`integrations/centreon_logs.py` le **rejoue** dans l'ordre pour en déduire
le dernier état de chaque hôte et de chaque service. Il sert à **visualiser
en local** ; en production, Centreon est lu par son API. Le fichier est exclu
de git.

```bash
# 1. Dans .env : donner au collecteur l'accès en lecture au dossier database/
#    COMPOSE_FILE=docker-compose.yml;docker-compose.dumps.yml
#    COMPOSE_PATH_SEPARATOR=;
# 2. Dans .env : brancher Centreon sur l'export
#    CENTREON_API_URL=file:///srv/dumps/alertes.sql
# 3. Prendre en compte la configuration
docker compose up -d collector backend
```

Ce que l'export donne et ne donne pas :

- **12 hôtes**, dont 11 avec leur adresse IP ; aucun groupe, donc ni site ni
  région : ils sont comptés sous « Région non renseignée ».
- **Aucune alerte** : toutes les lignes de l'export fourni sont à l'état OK.
  Un export sans filtre de statut (`SELECT * FROM logs WHERE ctime >= …`)
  ferait apparaître les alertes encore ouvertes à la fin de l'export.
- L'état affiché est celui de la **fin de l'export** (27/10/2026), figé.

### 3.3 Outils de laboratoire

Instances locales **aux mêmes versions que la production** de l'agence (et un
simulateur pour NSP). Les URL et comptes sont déjà dans `.env.example`.

```bash
# Zabbix et iTop (~2 Go de RAM)
docker compose --profile zabbix --profile itop up -d
docker compose logs -f itop                              # attendre la fin de l'installation
docker compose --profile provision run --rm provision    # déclarer les machines à superviser

# Centreon (~2 Go de plus, à part)
docker compose --profile centreon up -d
docker compose exec centreon /usr/local/bin/provision-lab

# Nagios : son inventaire est le fichier tools/nagios/noc-lab.cfg
docker compose --profile nagios up -d nagios

# Simulateur Nokia NSP (Nokia ne distribue pas NSP)
docker compose --profile nsp up -d --build nsp-sim

# Réseau de site simulé (SNMP, trafic, pannes) pour Zabbix et Centreon
docker compose --profile netlab up -d
```

Pour le **simulateur NSP**, dans `.env` :

```ini
NSP_API_URL=http://nsp-sim:8080
NSP_API_USER=admin
NSP_API_PASSWORD=NspLab!2026
NSP_FM_MODE=yang
```

Il sert 8 équipements du réseau de transport (préfixés `LAB-`) et leurs
alarmes ; `LAB-GAOUA-WAVENCE-01` tombe seul 15 minutes au début de chaque
heure. Lever ou effacer une alarme à la main :

```bash
curl http://localhost:8086/_sim/state
curl -X POST http://localhost:8086/_sim/alarms -H 'Content-Type: application/json' \
     -d '{"ne_id":"LAB-NSP-7","severity":"critical","text":"Coupure fibre"}'
curl -X DELETE http://localhost:8086/_sim/alarms/<id>
```

Le simulateur montre comment le NOC affiche des données NSP ; il **ne prouve
pas** que le connecteur fonctionne avec le NSP de l'agence.

Après avoir lancé un outil ou changé `.env` : `docker compose up -d collector
backend`. Accès aux interfaces : [§ 8](#8-adresses-et-ports). Détails et
pièges connus : **[tools/README.md](tools/README.md)**.

### 3.4 Outils réels de l'agence

Dans `.env`, remplacer le bloc « laboratoire local » (section 4) par le bloc
« production » (section 5) : URL des **API** des outils de l'agence et
**comptes en lecture seule**. Ne jamais mélanger les deux blocs, et ne pas
charger `docker-compose.dumps.yml` (`COMPOSE_FILE`) ni de profil local.

Avant la mise en service, **vérifier ce que chaque API renvoie réellement** :

```bash
docker compose run --rm collector python -m collector.probe              # tous les outils
docker compose run --rm collector python -m collector.probe netxms nsp   # certains
docker compose run --rm -v "$PWD:/out" collector \
  python -m collector.probe --json /out/recette.json                     # rapport transmissible
```

Le diagnostic lit les outils sans rien publier et donne : version, nombre
d'équipements et d'alertes, part localisée et part des alertes rattachées à
un équipement, faits de fiche, et pour NetXMS par API les noms des champs
reçus. Le rapport JSON ne contient aucun secret. Critères d'acceptation et
résultats de la recette locale : [docs/09](docs/09-exploitation.md#recette-des-connecteurs).

Enfin, **faire superviser le NOC lui-même par Zabbix** : importer
`monitoring/zabbix/noc_resina_by_http.yaml` dans le Zabbix de l'agence
([docs/09](docs/09-exploitation.md#faire-superviser-le-noc-par-zabbix)).

---

## 4. Mettre à jour une installation existante

Mêmes commandes sur un poste (Git Bash) et sur une **VM Ubuntu**, depuis le
dossier du projet. Si l'utilisateur n'est pas dans le groupe `docker`,
préfixer par `sudo`. Remplacer `noc` / `noc` si `POSTGRES_USER` /
`POSTGRES_DB` diffèrent dans `.env`.

```bash
# 1. Récupérer le code
git pull

# 2. Sauvegarder la base du NOC
docker compose exec -T postgres pg_dump -U noc -d noc --clean --if-exists \
  > sauvegarde_noc_$(date +%F).sql

# 3. Arrêter ce qui écrit dans la base
docker compose stop collector backend

# 4. Mettre le schéma à jour (sans danger, rejouable)
docker compose exec -T postgres psql -U noc -d noc -v ON_ERROR_STOP=1 \
  < backend/sql/schema.sql

# 5. Aligner la révision Alembic (révision courante : 0006)
docker compose exec -T postgres psql -U noc -d noc \
  -c "UPDATE alembic_version SET version_num = '0006_history_journal'"

# 6. Reconstruire et relancer
docker compose up -d --build

# 7. Vérifier
docker compose ps
curl -sk https://localhost:8443/api/health
docker compose exec -T postgres psql -U noc -d noc -c "\dt hist_*"
```

> ⚠️ Depuis la version du 29 octobre 2026, le rejeu de `schema.sql`
> **supprime** les tables qui ne sont plus alimentées (`ops_alert_state`,
> `ops_alert_timeline`, `ops_manual_incident`, `ops_maintenance_window`,
> `ops_field_intervention`) **avec leur contenu**, et crée le journal
> historique (`hist_state`, `hist_alert`) et la file des notifications à
> retenter (`ops_notification_retry`). D'où la sauvegarde de l'étape 2.

Sur une VM, mettre la sauvegarde à l'abri depuis son poste :
`scp utilisateur@vm:/chemin/noc/sauvegarde_noc_*.sql .`

En PowerShell, l'étape 4 s'écrit :
`Get-Content backend/sql/schema.sql -Raw | docker compose exec -T postgres psql -U noc -d noc -v ON_ERROR_STOP=1`.

`bash deployment.sh` arrête puis relance **toute** la pile ; il ne met pas le
schéma à jour.

---

## 5. Tester les alertes par courriel

La plateforme envoie un courriel à chaque nouvelle alerte grave (critique ou
majeure), retente un envoi échoué, et regroupe une rafale (plus de 10 alertes
d'un coup) en un seul message. Pour tester sans écrire à personne, un faux
serveur SMTP est fourni :

```bash
docker compose --profile mail up -d mailpit
```

Dans `.env` :

```ini
NOTIFICATIONS_ENABLED=true
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_USE_TLS=false
```

Puis `docker compose up -d backend`. Les courriels se lisent sur
**<http://localhost:8025>**.

Côté interface : écran *Utilisateurs* → renseigner l'adresse d'un compte et
cocher « Recevoir les alertes » → bouton **Envoyer un test** dans le panneau
*Alertes par courriel*. Pour provoquer une vraie alerte : lever une alarme
dans le simulateur NSP (§ 3.3) ou arrêter un conteneur supervisé.

En production, remplacer `SMTP_*` par le relais de messagerie de l'agence et
refaire le test.

---

## 6. Commandes du quotidien

| Besoin | Commande |
|---|---|
| État des conteneurs | `docker compose ps` |
| Santé de la chaîne (Redis, collecteur, base, sources, notifications) | `curl -sk https://localhost:8443/api/health` |
| Journaux d'un service | `docker compose logs -f --tail 100 collector` (ou `backend`, `nginx`…) |
| Redémarrer un service | `docker compose restart backend` |
| Prendre en compte une modification de `.env` | `docker compose up -d collector backend` |
| Lancer un outil local | `docker compose --profile nagios up -d nagios` (ou `nsp`, `netxms`, `mail`…) |
| Mettre à jour le code et la base | [§ 4](#4-mettre-à-jour-une-installation-existante) |
| Arrêter **sans rien perdre** | `docker compose down` |
| Réinitialiser un mot de passe | `docker compose exec backend python scripts/create_user.py -u <identifiant> --reset-password -p "<nouveau>"` |
| Lister les comptes | `docker compose exec backend python scripts/create_user.py --list` |
| Mettre à jour le schéma de la base | `docker compose exec -T postgres psql -U noc -d noc -v ON_ERROR_STOP=1 < backend/sql/schema.sql` |
| Sauvegarder la base du NOC | `docker compose exec -T postgres pg_dump -U noc -d noc --clean --if-exists > sauvegarde_noc.sql` |
| Restaurer une sauvegarde | `docker compose exec -T postgres psql -U noc -d noc < sauvegarde_noc.sql` |
| Vérifier ce qu'un outil renvoie, sans rien publier | `docker compose run --rm collector python -m collector.probe <outil>` |
| Compléter les bilans journaliers manquants depuis le journal | `docker compose exec collector python -m collector.history backfill --days 30` |
| Recalculer les bilans d'une période | `docker compose exec collector python -m collector.history rebuild-daily --from 2026-10-01 --to 2026-10-31 --overwrite` |
| Notifications en attente de nouvel envoi | `docker compose exec -T postgres psql -U noc -d noc -c "select alert_key, channel, status, attempts, last_error from ops_notification_retry order by id desc limit 10"` |

Lancer les **tests** (sans base ni outil réels) :

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv/Scripts/activate sous Windows
pip install -r requirements-dev.txt                 # + `pip install tzdata` sous Windows
PYTHONPATH=.. python -m pytest -q tests             # PYTHONPATH="..;." sous Windows
cd ../frontend && npm install && npm run lint && npm run build
```

> ⛔ **Ne jamais lancer `docker compose down -v`.** L'option `-v` supprime les
> volumes : tous les comptes, objectifs SLA, journal d'audit, bilans
> journaliers et **tout l'historique de disponibilité** sont perdus, et plus
> personne ne peut se connecter.
>
> ⛔ **Ne pas vider Redis** (`FLUSHALL`) en exploitation : le NOC croirait à
> un premier démarrage et ne notifierait pas les alertes du cycle suivant.

---

## 7. Configuration : les variables essentielles

`.env.example` documente chaque variable. Les plus importantes :

| Variable | Rôle | Valeur par défaut |
|---|---|---|
| `SECRET_KEY` | Signature des jetons de connexion (≥ 32 caractères) | — (obligatoire) |
| `POSTGRES_PASSWORD` | Mot de passe de la base du NOC | — (obligatoire) |
| `REDIS_PASSWORD` | Mot de passe de Redis | — (obligatoire) |
| `COLLECT_INTERVAL_S` | Cadence de lecture des outils, en secondes. **C'est la charge imposée à la production** : une série de requêtes par outil par intervalle. | `300` |
| `<OUTIL>_API_URL`, `_USER`, `_PASSWORD`, `_TOKEN` | Accès à chaque outil. URL vide = outil désactivé. En production, toujours l'URL de l'API ; `postgresql://…` (NetXMS) et `file://…` (Centreon) ne servent qu'aux exports locaux. | laboratoire local |
| `NETXMS_SITE_ATTRIBUTE` | NetXMS par API : attribut personnalisé portant le site administratif (sinon, la ville) | vide |
| `NETXMS_COLLECT_INTERFACES` | NetXMS par API : lire les interfaces (liens, capacité) — la lecture la plus lourde | `true` |
| `NAGIOS_MODE`, `NSP_FM_MODE` | Mode d'accès Nagios (`statusjson`, `livestatus`) et NSP (`yang`, `classic`) | `unknown` |
| `HISTORY_ENABLED` | Journal historique (disponibilité sur la durée, liens, rattrapage des bilans) | `true` |
| `HISTORY_RETENTION_DAYS` | Conservation du journal, en jours (0 = indéfiniment) | `0` |
| `ROLLUP_HOUR`, `ROLLUP_RETRY_S` | Heure du bilan journalier ; délai entre deux essais s'il échoue | `1`, `900` |
| `NOTIFICATIONS_ENABLED` | Envoi automatique des courriels et SMS | `false` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` | Serveur de messagerie | vide |
| `NOTIFY_SEVERITIES` | Gravités qui déclenchent une notification | `critical,high` |
| `NOTIFY_RETRY_MAX_ATTEMPTS`, `NOTIFY_RETRY_MAX_AGE_MIN` | Nouvelles tentatives d'un envoi échoué : nombre, âge maximal de l'alerte | `6`, `360` |
| `NOTIFY_BURST_MAX` | Au-delà, une rafale d'alertes graves part en un seul message | `10` |
| `REFRESH_COOKIE_SECURE` | `true` dès que l'accès se fait en HTTPS | `true` |
| `CORS_ORIGINS`, `DASHBOARD_URL` | Adresse publique de l'interface (à adapter sur un serveur) | `localhost` |
| `COMPOSE_PROFILES`, `COMPOSE_FILE` | **Local seulement** : outils lancés d'office, accès aux exports (`docker-compose.dumps.yml`) | vide |

> ⚠️ **Ne jamais écrire deux fois la même variable dans `.env`.** Docker
> Compose garde silencieusement la dernière, ce qui produit des pannes dont le
> message ne parle jamais de configuration.

---

## 8. Adresses et ports

| Service | Adresse depuis le poste | Identifiants |
|---|---|---|
| **Interface NOC** | <https://localhost:8443> (et <http://localhost:8888>, redirigé) | comptes créés dans le NOC |
| Sonde de santé | <https://localhost:8443/api/health> | publique |
| Base du NOC (PostgreSQL) | `127.0.0.1:5436`, base `noc` | `noc` / `POSTGRES_PASSWORD` |
| Base NetXMS restaurée | `127.0.0.1:5438`, base `netxms` | `netxms` / `netxms` (lecture : `noc_reader`) |
| Mailpit (courriels de test) | <http://localhost:8025> | — |
| Zabbix de laboratoire | <http://localhost:8081> | `Admin` / `zabbix` |
| iTop de laboratoire | <http://localhost:8082> | `admin` / `ITOP_ADMIN_PASSWORD` |
| Centreon de laboratoire | <http://localhost:8084/centreon> | `admin` / `CENTREON_API_PASSWORD` |
| Nagios de laboratoire | <http://localhost:8085/nagios> | `nagiosadmin` / `NAGIOS_API_PASSWORD` |
| Simulateur NSP | <http://localhost:8086/_sim/state> | pilotage sans compte ; API : `NSP_API_USER` / `NSP_API_PASSWORD` |

La documentation interactive de l'API (Swagger) est **fermée par défaut**, et
le backend n'a plus de port publié (seul nginx le joint). Pour la consulter en
développement : `API_DOCS_ENABLED=true` dans `.env`, puis un fichier
`docker-compose.override.yml` **non versionné** publiant temporairement le
backend sur la boucle locale :

```yaml
services:
  backend:
    ports:
      - "127.0.0.1:8000:8000"
```

`docker compose up -d backend`, puis <http://127.0.0.1:8000/docs>.

Nginx joint le backend par un réseau privé dédié. Si le sous-réseau
`172.31.250.0/29` est déjà utilisé sur l'hôte, adapter ensemble
`API_PROXY_SUBNET` et `NGINX_API_PROXY_IP` dans `.env`; l'adresse choisie
est appliquée à nginx dans Compose et transmise comme seule IP de proxy de
confiance au backend.

---

## 9. Problèmes fréquents

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Identifiants invalides » alors que le compte a été créé | Les volumes ont été supprimés (`down -v`) et la base est vide, **ou** le mot de passe a été saisi de façon masquée sous Windows | `create_user.py --list` pour vérifier ; recréer ou réinitialiser avec `-p` |
| Le backend redémarre en boucle | `SECRET_KEY` absente ou trop courte | La renseigner (≥ 32 caractères) |
| nginx ne démarre pas | Certificat absent | `bash nginx/generate_cert.sh` |
| Tableau de bord vide | Aucune source branchée, ou collecteur arrêté | Écran *Collecte ETL* ; `docker compose logs collector` |
| « Collecte interrompue » | Le collecteur ne publie plus depuis 15 min | `docker compose restart collector`, puis lire ses journaux |
| *Collecte ETL* : Nagios « En erreur » | URL renseignée mais conteneur de laboratoire non démarré | `docker compose --profile nagios up -d nagios` |
| *Collecte ETL* : NSP « Non configuré » | `NSP_API_URL` vide ou `NSP_FM_MODE=unknown` | En local : simulateur (§ 3.3) ; en production : l'instance de l'agence |
| Journaux du collecteur : « Journal historique non mis à jour » ; fiche équipement : « Historique indisponible » | Schéma pas mis à jour (tables `hist_*` absentes) | [§ 4](#4-mettre-à-jour-une-installation-existante), étapes 2 à 6 |
| NetXMS (dump) : fiche technique vide (inventaire, liens) | Droits du compte `noc_reader` d'avant la fiche technique | Rejouer `netxms_readonly_role.sql` (§ 3.1) |
| Centreon (export) : « export introuvable » | `docker-compose.dumps.yml` non chargé | `COMPOSE_FILE` dans `.env` (§ 3.2) |
| Déconnexion au bout de 30 min | `REFRESH_COOKIE_SECURE=true` avec un accès en `http://` | Accéder en HTTPS, ou mettre `false` en local |
| Aucun courriel reçu | Voir la liste de contrôle dans [docs/06](docs/06-alertes-et-notifications.md#diagnostic--pourquoi-je-ne-reçois-rien) | — |
| `no such file or directory` au lancement d'un script `.sh` dans un conteneur | Fins de ligne Windows (CRLF) | Le `.gitattributes` force LF ; re-cloner ou convertir le fichier |
| Un outil de laboratoire affiche « PostgreSQL server is not available » | Variable dupliquée dans `.env`, ou mot de passe changé après la création du volume | Voir [tools/README.md](tools/README.md#pièges-rencontrés-et-comment-les-reconnaître) |

---

## 10. Aller plus loin

| Document | Contenu |
|---|---|
| **[docs/README.md](docs/README.md)** | Documentation complète : comprendre le métier, l'architecture, le code, la sécurité, l'exploitation |
| [docs/11-donnees-et-indicateurs.md](docs/11-donnees-et-indicateurs.md) | D'où vient chaque chiffre affiché, quand il change, comment il est calculé |
| [docs/12-reprise-du-projet.md](docs/12-reprise-du-projet.md) | Reprendre le projet : quoi récupérer, comment démarrer, pièges, liste avant production |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Le raisonnement derrière les choix d'architecture |
| [tools/README.md](tools/README.md) | Les outils de laboratoire et le simulateur NSP : versions, installation, pièges |
| [monitoring/zabbix/](monitoring/zabbix/) | Modèle Zabbix pour superviser le NOC lui-même |
| [.env.example](.env.example) | Chaque variable de configuration, commentée |

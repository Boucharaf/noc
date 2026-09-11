# Plateforme NOC RESINA

Tableau de bord du **centre de supervision (NOC)** du réseau de
l'administration burkinabè (RESINA, exploité par l'ANPTIC). La plateforme lit
les outils de supervision existants — Zabbix, Centreon, iTop, NetXMS, et à
terme Nagios et Nokia NSP — et présente un écran par métier : Directeur,
Chef NOC, Technicien, Agent terrain.

> **Ce fichier explique comment installer et faire tourner le projet.**
> Pour **comprendre** le projet (métier, architecture, code, sécurité), lire
> la documentation : **[docs/README.md](docs/README.md)**.

---

## Sommaire

1. [Prérequis](#1-prérequis)
2. [Installation et premier lancement](#2-installation-et-premier-lancement)
3. [Choisir ses sources de données](#3-choisir-ses-sources-de-données)
4. [Tester les alertes par courriel](#4-tester-les-alertes-par-courriel)
5. [Commandes du quotidien](#5-commandes-du-quotidien)
6. [Configuration : les variables essentielles](#6-configuration--les-variables-essentielles)
7. [Adresses et ports](#7-adresses-et-ports)
8. [Problèmes fréquents](#8-problèmes-fréquents)
9. [Aller plus loin](#9-aller-plus-loin)

---

## 1. Prérequis

| Élément | Détail |
|---|---|
| **Docker** avec Compose v2 | Docker Desktop (Windows, macOS) ou Docker Engine (Linux). Toute la plateforme tourne en conteneurs : rien d'autre à installer pour la faire fonctionner. |
| **Mémoire allouée à Docker** | 4 Go pour la plateforme seule ; **8 Go** avec la base NetXMS et un ou deux outils de laboratoire ; 12 Go et plus avec Zabbix + iTop + Centreon. |
| **Disque** | 10 Go pour la plateforme ; +2 Go pour la base NetXMS restaurée ; +5 Go pour les outils de laboratoire. |
| **Git** | Pour récupérer le code. |
| **Un terminal bash** | Les scripts `.sh` du dépôt sont en bash. Sous Windows : **Git Bash** (installé avec Git). |
| **Ports libres** | 8443 et 8888 (interface), 5436 (base du NOC, publiée sur 127.0.0.1 seulement). |

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

```bash
docker compose up -d --build
```

Le premier lancement construit les images (quelques minutes). Vérifier que
tout est « healthy » :

```bash
docker compose ps
```

### Étape 5 — Créer le premier compte (Chef NOC)

Aucun compte n'existe au départ, et l'interface exige d'être connecté pour en
créer. Ce script crée le premier :

```bash
docker compose exec backend python scripts/create_user.py \
    -u chefnoc -r chef_noc -n "Chef NOC" -p "UnMotDePasseSolide"
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
| Technicien | Console d'exploitation (traitement des alertes) |
| Agent terrain | Tournée (interventions, signalement de pannes) |

À ce stade, **le tableau de bord est vide** : aucune source de données n'est
branchée. C'est normal — voir la section suivante.

---

## 3. Choisir ses sources de données

La plateforme ne stocke pas les équipements ni les alertes : elle les lit
chez les outils de supervision. Un outil s'active par la **seule présence de
son URL** dans `.env` (`<OUTIL>_API_URL`). Quatre situations possibles :

| Situation | Données affichées | Mise en place |
|---|---|---|
| **A. Aucune source** | Aucune (écrans vides) | Rien à faire |
| **B. Dump NetXMS de production** | 1 409 équipements et 791 alarmes réels, **figés au 07/08/2026** | [§ 3.1](#31-base-netxms-restaurée-depuis-le-dump) |
| **C. Outils de laboratoire** | Les conteneurs de la pile, supervisés par de vrais Zabbix, iTop et Centreon locaux | [§ 3.2](#32-outils-de-laboratoire-zabbix-itop-centreon) |
| **D. Outils réels de l'agence** | Le vrai réseau, en direct | [§ 3.3](#33-outils-réels-de-lagence) |

Les situations B, C et D se combinent : les équipements de plusieurs outils
sont fusionnés dans un même parc.

### 3.1 Base NetXMS restaurée depuis le dump

Le fichier `database/netxmsbd07082026.sql` (356 Mo, **exclu de git** car il
contient des données de production) doit être copié à la main dans
`database/`.

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

### 3.2 Outils de laboratoire (Zabbix, iTop, Centreon)

Instances locales, **aux mêmes versions que la production** de l'agence. Elles
sont lourdes : les lancer par profil.

```bash
docker compose --profile zabbix --profile itop up -d     # ~2 Go de RAM
docker compose logs -f itop                              # attendre la fin de l'installation
docker compose --profile provision run --rm provision    # déclarer les machines à superviser

docker compose --profile centreon up -d                  # ~2 Go de plus, à part
docker compose exec centreon /usr/local/bin/provision-lab
```

Les URL et comptes de ces outils sont déjà dans `.env.example`. Accès aux
interfaces : voir [§ 7](#7-adresses-et-ports). Détails et pièges connus :
**[tools/README.md](tools/README.md)**.

### 3.3 Outils réels de l'agence

Dans `.env`, remplacer le bloc « laboratoire local » (section 4) par le bloc
« production » (section 5) : URL des outils de l'agence et **comptes en
lecture seule**. Ne jamais mélanger les deux blocs.

Pour NetXMS, deux accès sont possibles, sans changer de code :

- **par son API Web** : `NETXMS_API_URL=https://…` et un compte NetXMS ;
- **par sa base, en lecture seule** : l'administrateur de l'agence exécute
  `database/netxms_readonly_role.sql`, puis
  `NETXMS_API_URL=postgresql://<hôte>:5432/netxms?sslmode=verify-full`.

---

## 4. Tester les alertes par courriel

La plateforme envoie un courriel à chaque nouvelle alerte grave (critique ou
majeure). Pour tester sans écrire à personne, un faux serveur SMTP est fourni :

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
*Alertes par courriel*.

En production, remplacer `SMTP_*` par le relais de messagerie de l'agence et
refaire le test.

---

## 5. Commandes du quotidien

| Besoin | Commande |
|---|---|
| État des conteneurs | `docker compose ps` |
| Santé de la chaîne | `curl -sk https://localhost:8443/api/health` |
| Journaux d'un service | `docker compose logs -f --tail 100 collector` (ou `backend`, `nginx`…) |
| Redémarrer un service | `docker compose restart backend` |
| Prendre en compte une modification de `.env` | `docker compose up -d collector backend` |
| Mettre à jour le code | `git pull && bash deployment.sh` |
| Arrêter **sans rien perdre** | `docker compose down` |
| Réinitialiser un mot de passe | `docker compose exec backend python scripts/create_user.py -u <identifiant> --reset-password -p "<nouveau>"` |
| Lister les comptes | `docker compose exec backend python scripts/create_user.py --list` |
| Mettre à jour le schéma de la base | `docker compose exec -T postgres psql -U noc -d noc < backend/sql/schema.sql` (sans danger, rejouable) |
| Sauvegarder la base du NOC | `docker compose exec -T postgres pg_dump -U noc -d noc --clean --if-exists > sauvegarde_noc.sql` |
| Restaurer une sauvegarde | `docker compose exec -T postgres psql -U noc -d noc < sauvegarde_noc.sql` |

> ⛔ **Ne jamais lancer `docker compose down -v`.** L'option `-v` supprime les
> volumes : tous les comptes, acquittements, notes et maintenances sont
> perdus, et plus personne ne peut se connecter.

---

## 6. Configuration : les variables essentielles

`.env.example` documente chaque variable. Les plus importantes :

| Variable | Rôle | Valeur par défaut |
|---|---|---|
| `SECRET_KEY` | Signature des jetons de connexion (≥ 32 caractères) | — (obligatoire) |
| `POSTGRES_PASSWORD` | Mot de passe de la base du NOC | — (obligatoire) |
| `REDIS_PASSWORD` | Mot de passe de Redis | — (obligatoire) |
| `COLLECT_INTERVAL_S` | Cadence de lecture des outils, en secondes. **C'est la charge imposée à la production** : une requête par outil par intervalle. | `300` |
| `<OUTIL>_API_URL`, `_USER`, `_PASSWORD`, `_TOKEN` | Accès à chaque outil. URL vide = outil désactivé. | laboratoire local |
| `NOTIFICATIONS_ENABLED` | Envoi automatique des courriels et SMS | `false` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` | Serveur de messagerie | vide |
| `NOTIFY_SEVERITIES` | Gravités qui déclenchent une notification | `critical,high` |
| `REFRESH_COOKIE_SECURE` | `true` dès que l'accès se fait en HTTPS | `false` |
| `CORS_ORIGINS`, `DASHBOARD_URL` | Adresse publique de l'interface (à adapter sur un serveur) | `localhost` |

> ⚠️ **Ne jamais écrire deux fois la même variable dans `.env`.** Docker
> Compose garde silencieusement la dernière, ce qui produit des pannes dont le
> message ne parle jamais de configuration.

---

## 7. Adresses et ports

| Service | Adresse depuis le poste | Identifiants |
|---|---|---|
| **Interface NOC** | <https://localhost:8443> (et <http://localhost:8888>, redirigé) | comptes créés dans le NOC |
| Base du NOC (PostgreSQL) | `127.0.0.1:5436`, base `noc` | `noc` / `POSTGRES_PASSWORD` |
| Base NetXMS restaurée | `127.0.0.1:5438`, base `netxms` | `netxms` / `netxms` (lecture : `noc_reader`) |
| Mailpit (courriels de test) | <http://localhost:8025> | — |
| Zabbix de laboratoire | <http://localhost:8081> | `Admin` / `zabbix` |
| iTop de laboratoire | <http://localhost:8082> | `admin` / `ITOP_ADMIN_PASSWORD` |
| Centreon de laboratoire | <http://localhost:8084/centreon> | `admin` / `CENTREON_API_PASSWORD` |

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

---

## 8. Problèmes fréquents

| Symptôme | Cause probable | Solution |
|---|---|---|
| « Identifiants invalides » alors que le compte a été créé | Les volumes ont été supprimés (`down -v`) et la base est vide, **ou** le mot de passe a été saisi de façon masquée sous Windows | `create_user.py --list` pour vérifier ; recréer ou réinitialiser avec `-p` |
| Le backend redémarre en boucle | `SECRET_KEY` absente ou trop courte | La renseigner (≥ 32 caractères) |
| nginx ne démarre pas | Certificat absent | `bash nginx/generate_cert.sh` |
| Tableau de bord vide | Aucune source branchée, ou collecteur arrêté | Écran *Collecte ETL* ; `docker compose logs collector` |
| « Collecte interrompue » | Le collecteur ne publie plus depuis 15 min | `docker compose restart collector`, puis lire ses journaux |
| Déconnexion au bout de 30 min | `REFRESH_COOKIE_SECURE=true` avec un accès en `http://` | Accéder en HTTPS, ou mettre `false` en local |
| Aucun courriel reçu | Voir la liste de contrôle dans [docs/06](docs/06-alertes-et-notifications.md#diagnostic--pourquoi-je-ne-reçois-rien) | — |
| `no such file or directory` au lancement d'un script `.sh` dans un conteneur | Fins de ligne Windows (CRLF) | Le `.gitattributes` force LF ; re-cloner ou convertir le fichier |
| Un outil de laboratoire affiche « PostgreSQL server is not available » | Variable dupliquée dans `.env`, ou mot de passe changé après la création du volume | Voir [tools/README.md](tools/README.md#pièges-rencontrés-et-comment-les-reconnaître) |

---

## 9. Aller plus loin

| Document | Contenu |
|---|---|
| **[docs/README.md](docs/README.md)** | Documentation complète : comprendre le métier, l'architecture, le code, la sécurité, l'exploitation |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Le raisonnement derrière les choix d'architecture |
| [tools/README.md](tools/README.md) | Les outils de laboratoire : versions, installation, pièges |
| [.env.example](.env.example) | Chaque variable de configuration, commentée |

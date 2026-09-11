# 5. Comptes, rôles et sécurité

## Les quatre rôles

| Rôle (code) | Libellé | Vocation |
|---|---|---|
| `directeur` | Directeur | Pilotage : indicateurs, SLA, rapports |
| `chef_noc` | Chef NOC | Salle de supervision : répartition du travail, maintenances, **gestion des comptes** |
| `technicien` | Technicien NOC | Traitement des alertes |
| `agent_terrain` | Agent terrain | Interventions sur site, signalement de pannes |

Un rôle est défini à **trois endroits qui doivent rester identiques** :
`backend/app/core/config.py` (`VALID_ROLES`), `backend/app/schemas/users.py`
(`RoleEnum`) et `frontend/src/lib/permissions.js` (`ROLES`).

## Qui peut faire quoi

**La seule autorisation qui compte est celle du backend.** Chaque route vérifie
le rôle (`require_role(...)` dans `backend/app/dependencies/auth.py`). Le
fichier `frontend/src/lib/permissions.js` ne sert qu'à masquer les boutons
inutiles ; il ne protège rien.

Droits réellement appliqués par le backend :

| Action | Directeur | Chef NOC | Technicien | Agent terrain |
|---|:---:|:---:|:---:|:---:|
| Consulter l'état du réseau, les alertes, les équipements, les SLA | ✅ | ✅ | ✅ | ✅ |
| Acquitter, affecter, résoudre une alerte | ✅ | ✅ | ✅ | — |
| Ajouter une note à une alerte | ✅ | ✅ | ✅ | ✅ |
| Signaler / clore un incident manuel | ✅ | ✅ | ✅ | ✅ |
| Créer / supprimer une fenêtre de maintenance | ✅ | ✅ | — | — |
| Modifier les cibles SLA | ✅ | ✅ | — | — |
| Programmer une intervention terrain | ✅ | ✅ | ✅ | — |
| Faire avancer une intervention, rendre compte | ✅ | ✅ | ✅ | ✅ |
| Télécharger le rapport mensuel | ✅ | ✅ | — | — |
| **Créer un compte, attribuer un rôle, désactiver, réinitialiser un mot de passe ou un PIN** | — | ✅ | — | — |
| Couper les sessions d'un utilisateur | — | ✅ | — | — |
| Consulter et tester la configuration des courriels | — | ✅ | — | — |
| **Modifier ses propres identifiants** (identifiant, nom, téléphone, courriel, mot de passe, abonnement aux alertes) | ✅ | ✅ | ✅ | ✅ |
| Modifier **son propre rôle** | — | — | — | — |

> Quelques écarts existent entre ce tableau et ce que l'interface affiche (par
> exemple, l'interface propose au technicien de créer une maintenance, que le
> backend refuse). Ils sont listés au [chapitre 10](10-etat-du-projet.md).

## La gestion des comptes

### Le premier compte

Au premier démarrage, la base est vide et l'API exige d'être connecté en Chef
NOC pour créer un compte. Le script `backend/scripts/create_user.py` casse
cette boucle :

```bash
docker compose exec backend python scripts/create_user.py -u chefnoc -r chef_noc -n "Chef NOC" -p "…"
```

Il sert aussi au dépannage : `--reset-password`, `--list`, et `--role-set`
(un compte par rôle, pour une recette).

### Ensuite, tout se fait dans l'interface

- **Le Chef NOC** (écran *Utilisateurs*) crée les comptes avec un mot de passe
  provisoire, attribue et change les rôles, réinitialise un mot de passe
  oublié, définit le PIN d'un agent terrain, désactive un compte, et choisit
  qui reçoit les alertes par courriel.
- **Chaque utilisateur** (écran *Mon compte*) modifie ses identifiants. Changer
  d'identifiant exige de saisir son mot de passe actuel.

### Règles de protection

| Règle | Raison |
|---|---|
| Un compte n'est **jamais supprimé**, seulement désactivé | Supprimer effacerait la traçabilité « qui a résolu cet incident ». |
| Un Chef NOC ne peut **ni changer son propre rôle, ni se désactiver** | Le dernier Chef NOC laisserait sinon la plateforme sans personne pour gérer les comptes. |
| Changer un rôle, désactiver un compte ou réinitialiser son mot de passe **coupe ses sessions** | Les droits changent immédiatement, sans attendre l'expiration des jetons. |
| Changer son mot de passe **ferme toutes ses sessions**, y compris l'actuelle | Geste attendu en cas de soupçon de compromission. |
| Le rôle est **relu en base à chaque requête** | Un compte rétrogradé ne garde pas ses anciens droits jusqu'à la fin de sa session. |

## L'authentification

```mermaid
sequenceDiagram
    participant N as Navigateur
    participant B as Backend
    participant R as Redis

    N->>B: POST /api/auth/login (identifiant, mot de passe)
    B->>B: vérifier l'empreinte bcrypt
    B->>R: enregistrer la session (jti, 7 jours)
    B-->>N: jeton d'accès (30 min, en mémoire) + cookie de rafraîchissement (httpOnly)
    loop chaque requête
        N->>B: Authorization: Bearer <jeton d'accès>
    end
    N->>B: POST /api/auth/refresh (cookie) — avant expiration
    B->>R: le jti est-il valide ? → rotation (nouveau jti)
    B-->>N: nouveau jeton d'accès + nouveau cookie
```

| Élément | Détail |
|---|---|
| Mots de passe | Empreinte **bcrypt**, **12 caractères minimum** (72 octets au plus). Les comptes créés avant gardent leur mot de passe jusqu'au prochain changement. |
| Verrouillage | Après **10 échecs** sur un compte depuis une même adresse, **50** sur un compte toutes adresses confondues, ou **30** depuis une adresse tous comptes confondus, la connexion est bloquée **15 minutes** (réglable : `LOGIN_*`). Le changement de mot de passe compte dans les mêmes compteurs. nginx limite en plus `/api/auth/login` et `/api/auth/pin-login` à 30 requêtes par minute par adresse. |
| Jeton d'accès | JWT signé avec `SECRET_KEY`, 30 minutes (`ACCESS_TOKEN_EXPIRE_MINUTES`), gardé **en mémoire** par le navigateur, jamais dans le stockage local. **Révoqué immédiatement** quand les sessions du compte sont coupées (mot de passe changé ou réinitialisé, rôle modifié, compte désactivé). |
| Jeton de rafraîchissement | JWT de 7 jours dans un cookie `httpOnly` limité à `/api/auth`. Chaque utilisation le remplace ; **réutiliser un ancien jeton coupe toutes les sessions du compte** (signe de vol). |
| Sessions | Enregistrées dans Redis : c'est ce qui permet de les révoquer. |
| Connexion par PIN | Réservée aux **agents terrain** (confort sur téléphone). **6 chiffres** pour tout nouveau code (les codes plus courts déjà définis restent acceptés jusqu'à leur remplacement). Deux comptes actifs ne peuvent pas partager un code. Empreinte **HMAC-SHA256** dont la clé est `SECRET_KEY` : changer cette clé oblige à redéfinir les PIN. Après **5 échecs**, l'adresse IP est bloquée **15 minutes**. Le PIN est un facteur faible, jamais disponible pour les autres rôles. |
| WebSocket | Le jeton est envoyé dans la **première trame**, pas dans l'URL (qui finirait dans les journaux du proxy). Le compte est relu en base à la connexion, et le flux est **fermé à l'expiration du jeton** ; le navigateur se reconnecte avec le jeton rafraîchi. |
| Liste des comptes | Tout compte connecté la lit (sélecteurs d'affectation), mais seul le **Chef NOC** reçoit téléphones, courriels, matricules et dates de connexion. |
| Transport | HTTPS par nginx (TLS 1.2 et 1.3). `REFRESH_COOKIE_SECURE=true` dès qu'on est en HTTPS. |

## Les données sensibles du projet

| Donnée | Où | Protection |
|---|---|---|
| Secrets de configuration (`SECRET_KEY`, `REDIS_PASSWORD`, mots de passe des bases, des outils, du SMTP) | `.env` | Exclu de git. Ne jamais le copier d'un environnement à l'autre : chaque environnement a ses propres secrets. **Aucune valeur réelle dans `.env.example`**, qui est versionné. |
| Dump NetXMS de production | `database/netxmsbd07082026.sql` | Exclu de git ; secrets purgés à la restauration ; base accessible sur `127.0.0.1` seulement. |
| Certificat TLS et sa clé | `nginx/certs/` | Exclu de git. |
| Comptes et travail d'exploitation | volume Docker `pgdata` | À sauvegarder régulièrement (chapitre 9). |

## Durcissement en place

| Couche | Mesure |
|---|---|
| Réseau | Le backend n'a **aucun port publié** : seul nginx le joint. La base du NOC et les interfaces des outils de laboratoire sont publiées sur `127.0.0.1` seulement. Redis exige un mot de passe (`REDIS_PASSWORD`). |
| Passerelle nginx | TLS 1.2/1.3 à suites AEAD, en-têtes `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` ; version masquée ; limitation de débit sur la connexion. |
| API | Documentation `/docs` fermée (`API_DOCS_ENABLED`). CORS limité aux origines, méthodes et en-têtes utiles, `*` refusé. Réponses `/api` en `Cache-Control: no-store`. Aucune trace d'exception renvoyée au client (santé, rapports). Paramètres bornés en longueur et énumérations ancrées. |
| Terrain | Un agent terrain ne lit et ne fait avancer que **ses** interventions. |
| Notifications | Un abonnement push n'est accepté que vers les services de push des navigateurs (`PUSH_ALLOWED_HOSTS`) : le backend ne peut pas être détourné vers le réseau interne. |
| Connecteurs | Redirections HTTP non suivies (un mot de passe iTop ne part pas vers un autre hôte) ; avertissement au démarrage si `*_VERIFY_SSL=false` sur une URL HTTPS. |
| Conteneurs | Processus Python sans privilèges, `no-new-privileges` sur les services de la plateforme, dépendances épinglées et auditées (`npm ci` pour le frontend). |

## Avant une mise en production

- **Certificat** : le certificat auto-signé est émis pour `noc.anptic.bf` et
  `localhost` ; le remplacer par un certificat de l'autorité de l'agence, puis
  **décommenter HSTS** dans `nginx/nginx.conf`.
- **`.env` de production neuf** : `SECRET_KEY`, `POSTGRES_PASSWORD` et
  `REDIS_PASSWORD` générés pour ce seul environnement ;
  `REFRESH_COOKIE_SECURE=true` ; `CORS_ORIGINS` réduit à l'adresse HTTPS du
  NOC ; `*_VERIFY_SSL=true` pour chaque outil source.
- **Publication de la base** : retirer le port `5436` de `docker-compose.yml`
  (sous Linux, Docker contourne `ufw` : la restriction doit vivre dans le
  fichier Compose). Ne pas lancer les profils de laboratoire.
- **Comptes de service** : sur les outils de l'agence, des comptes en lecture
  seule dédiés au NOC, jamais un compte d'administration.
- **Sauvegardes** : volume `pgdata` (chapitre 9).

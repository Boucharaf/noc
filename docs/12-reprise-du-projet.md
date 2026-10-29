# 12. Reprendre le projet

Ce chapitre s'adresse à **une équipe qui reprend le NOC** sans avoir
participé à sa construction. Il dit quoi récupérer, comment remettre un poste
en marche, comment vérifier que tout fonctionne, et quels pièges ont déjà
coûté du temps. Les autres chapitres donnent le détail ; celui-ci donne
l'ordre.

## 1. Ce qu'il faut récupérer auprès de l'équipe précédente

Rien de ceci n'est dans git, volontairement.

| Élément | Pourquoi | Où il va |
|---|---|---|
| Le fichier `.env` de chaque environnement (production, test) | Secrets : `SECRET_KEY`, mots de passe PostgreSQL et Redis, comptes des outils | Racine du dépôt, **jamais commité**, jamais copié d'un environnement à l'autre |
| Les comptes de service en lecture seule chez l'agence : Zabbix (jeton d'API), iTop, NetXMS, Centreon, Nagios, NSP | Seule source des données en production | `.env` (`<OUTIL>_API_URL`, `_USER`, `_PASSWORD`, `_TOKEN`) |
| Le certificat HTTPS de l'agence (ou la décision de garder l'auto-signé) | Accès sécurisé | `nginx/certs/` |
| Une sauvegarde récente de la base du NOC | Comptes, objectifs SLA, journal d'audit, bilans journaliers : rien d'autre ne les redonne | Restauration : [chapitre 9](09-exploitation.md#sauvegarder-et-restaurer) |
| Facultatif, pour travailler en local : le dump NetXMS et l'export du journal Centreon | Visualiser des données réelles sans accès à la production | `database/` (exclus de git) |
| Le document de l'agence *« informations essentielles par profil »* | Le besoin métier d'origine (quatre niveaux de lecture) | Racine du dépôt |
| Les contacts côté agence : administrateurs des outils, équipe sécurité | Droits d'accès, validation des connecteurs | — |

> Les commits `2d1131d` et `8fdf1d9` de l'historique contiennent des
> identifiants de production (Zabbix, iTop). Vérifier auprès de l'agence
> qu'ils ont bien été **changés** ([chapitre 10](10-etat-du-projet.md)).

## 2. Remettre un poste en marche

Suivre le [README](../README.md) dans l'ordre : prérequis, installation,
premier compte, puis une source de données. Pour un poste de développement
sans accès à la production, le plus parlant est :

1. le **dump NetXMS** (README § 3.1) : 1 409 équipements réels ;
2. l'**export du journal Centreon** (README § 3.2) : 12 serveurs ;
3. les **outils de laboratoire** (README § 3.3) : de vrais Zabbix, iTop et
   Centreon qui produisent de vraies alertes quand on arrête un conteneur.

Lancer les **tests** du backend ([chapitre 7](07-backend.md#tests)) :

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # .venv/Scripts/activate sous Windows
pip install -r requirements-dev.txt
PYTHONPATH=.. python -m pytest -q tests      # PYTHONPATH="..;." sous Windows
```

Sous **Windows**, deux écueils connus :

- les tests iTop échouent sur `zoneinfo` : installer la base des fuseaux
  horaires, `pip install tzdata` ;
- si `psycopg2` ne se charge pas (DLL absente), lancer les tests avec une
  base SQLite jetable : `NOC_DATABASE_URL=sqlite:///./test.db`.

Lancer le **lint et la construction** de l'interface :

```bash
cd frontend && npm install && npm run lint && npm run build
```

Les tests ne touchent ni base réelle ni outil réel. `test_integration.py` est
à part et refuse de tourner sans base dédiée.

## 3. Vérifier que tout fonctionne

Dans l'ordre, du plus large au plus fin :

1. **`docker compose ps`** : tous les services du cœur « healthy ».
2. **`curl -sk https://localhost:8443/api/health`** : Redis, collecteur, base.
3. **Écran *Collecte ETL*** : chaque outil joignable, dernier cycle récent,
   aucune erreur ; fusion, équipements vus par un seul outil, alertes sans
   équipement.
4. **Diagnostic de chaque outil**, sans rien publier :
   `docker compose run --rm collector python -m collector.probe <outil>`.
   Il dit combien d'équipements et d'alertes sont lus, quelle part est
   localisée, et (NetXMS) quels champs l'API renvoie réellement.
5. **Un cycle sain** dans les journaux du collecteur :
   `docker compose logs --tail 50 collector`.
6. **Le lendemain** : la ligne de la veille est apparue dans `kpi_daily`
   (tableau Direction, « Évolution sur 6 mois »).

## 4. Comprendre le système en une heure

| Pour comprendre… | Lire |
|---|---|
| Le métier, les écrans, le vocabulaire | [Chapitre 1](01-comprendre-le-projet.md) |
| Le trajet d'une donnée, de l'outil à l'écran | [Chapitre 2](02-architecture.md), puis [ARCHITECTURE.md](../ARCHITECTURE.md) pour le pourquoi |
| D'où vient chaque chiffre, quand il change, comment il est calculé | [Chapitre 11](11-donnees-et-indicateurs.md) |
| Comment chaque outil est lu | [Chapitre 4](04-sources-de-donnees.md) |
| Ce qui reste à faire, ce qui est fragile | [Chapitre 10](10-etat-du-projet.md) |

Dans le code, l'en-tête de chaque fichier explique **pourquoi** il est écrit
ainsi, souvent avec la panne que le choix évite. Les points d'entrée :
`collector/cycle.py` (le cycle), `collector/merge.py` (la fusion),
`integrations/base.py` (le contrat des connecteurs),
`backend/app/services/live_service.py` (la lecture de l'instantané),
`frontend/src/hooks/queries.js` (toutes les requêtes de l'interface).

## 5. Les règles à ne pas casser

Elles sont détaillées au [chapitre 2](02-architecture.md#principes-à-respecter-en-faisant-évoluer-le-projet).
En une ligne chacune :

1. **Ne pas recopier** les données des outils dans la base du NOC.
2. **En production, uniquement les API.** Les dumps et exports ne servent
   qu'en local.
3. **Lecture seule** envers les outils ; le NOC n'acquitte, n'affecte ni ne
   résout rien (ces gestes se font dans l'outil ou dans iTop).
4. **Charge constante** sur la production : aucun appel vers un outil
   déclenché par un rafraîchissement automatique d'écran.
5. **Un seul collecteur.**
6. **Ne jamais deviner** une donnée absente (site, état, gravité).
7. **Les droits se changent des deux côtés** : la route backend et
   `frontend/src/lib/permissions.js`.

## 6. Les pièges qui ont déjà coûté du temps

| Piège | Ce qui se passe | Parade |
|---|---|---|
| `docker compose down -v` | Supprime les volumes : comptes, objectifs SLA, audit, bilans perdus | Ne jamais utiliser `-v` ; sauvegarder chaque jour |
| Une variable écrite deux fois dans `.env` | Compose garde la dernière sans prévenir | Chercher les doublons avant de diagnostiquer |
| Rejouer `backend/sql/schema.sql` | **Supprime** les anciennes tables `ops_alert_state`, `ops_alert_timeline`, `ops_manual_incident`, `ops_maintenance_window`, `ops_field_intervention` et leur contenu | Sauvegarder avant ; c'est voulu, ces tables ne sont plus alimentées |
| Changer `POSTGRES_PASSWORD` après la création du volume | La base devient inaccessible | Changer le mot de passe dans PostgreSQL, pas seulement dans `.env` |
| Démarrer un serveur NetXMS sur le dump | Il enverrait les notifications de production à de vraies personnes | Ne jamais le faire ; le dump se lit par sa base |
| Un connecteur jamais confronté à l'outil réel (NetXMS par API, NSP) | Réponses de forme inattendue, équipements sans localité | `python -m collector.probe <outil>` avant la mise en service |
| L'export Centreon fourni | Il ne contient que des états OK : aucune alerte | Demander un export sans filtre de statut |
| Le fuseau d'iTop (`ITOP_TIMEZONE`) | S'il diffère de `config-itop.php`, tous les délais SLA sont décalés | Le vérifier sur l'instance |
| Un écran qui plante (« … is not a function ») | Décalage entre ce qu'attend l'écran et ce que renvoie l'API | [Chapitre 8](08-frontend.md#la-couche-de-compatibilité--à-connaître-absolument) |
| Une journée manquante dans les tendances | Écriture de nuit en échec, ou collecteur arrêté à l'heure du bilan | Rattrapée la nuit suivante depuis le journal ; sinon `python -m collector.history backfill` (chapitre 9). Un collecteur arrêté toute la journée laisse un vrai trou |

## 7. Avant la mise en production

- [ ] `.env` de production neuf, créé depuis `.env.example`, secrets
      générés pour cet environnement.
- [ ] Toutes les URL d'outils sont celles des **API** (`https://…`), aucune
      en `postgresql://` ni `file://` ; `docker-compose.dumps.yml` n'est pas
      chargé.
- [ ] Comptes des outils en **lecture seule**, validés par l'agence.
- [ ] `python -m collector.probe` sur chaque outil : équipements, alertes,
      localités et champs conformes (en particulier NetXMS et NSP).
- [ ] `ITOP_TIMEZONE`, `ITOP_TICKET_CLASSES`, `NAGIOS_MODE`, `NSP_FM_MODE`
      confirmés avec l'agence.
- [ ] Objectifs SLA du NOC comparés au contrat iTop (écran SLA).
- [ ] Certificat de l'agence, `REFRESH_COOKIE_SECURE=true`,
      `CORS_ORIGINS` et `DASHBOARD_URL` à l'adresse publique.
- [ ] Seul nginx est exposé ; PostgreSQL et le backend restreints.
- [ ] Courriel testé (*Utilisateurs* → *Envoyer un test*), puis
      `NOTIFICATIONS_ENABLED=true`.
- [ ] NOC supervisé par Zabbix (`monitoring/zabbix/`, chapitre 9),
      déclencheurs dirigés vers les médias de Zabbix, et notifications
      propres aux outils conservées pour les alertes critiques.
- [ ] Sauvegarde quotidienne de la base du NOC planifiée et une
      restauration essayée.
- [ ] Premier compte Chef NOC créé ; comptes nominatifs pour chaque
      utilisateur ; journal d'audit consulté.

## 8. Tenir la documentation à jour

À chaque évolution notable :

- **chapitre 10** : date, tests, limites, prochaines étapes ;
- **chapitre 11** si un chiffre affiché change d'origine ou de calcul ;
- le chapitre du domaine touché (sources, backend, frontend, sécurité) ;
- `.env.example` pour toute nouvelle variable, avec son commentaire.

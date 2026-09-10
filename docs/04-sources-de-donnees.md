# 4. Sources de données

La plateforme ne crée aucune donnée de supervision : elle la lit chez les
**outils sources** grâce à des **connecteurs** (`integrations/`).

## Le contrat d'un connecteur

Chaque connecteur hérite de `SourceClient` (`integrations/base.py`) et
implémente quatre méthodes :

| Méthode | Appelée par | Rôle |
|---|---|---|
| `check()` | collecteur, à chaque cycle | L'outil répond-il ? En combien de temps ? Quelle version ? Ne lève jamais : une panne se raconte par un `ToolHealth(reachable=False, error=…)`. |
| `fetch_nodes()` | collecteur | L'inventaire des équipements (`list[Node]`) |
| `fetch_alerts()` | collecteur | Les alertes **actives uniquement** (`list[Alert]`) |
| `fetch_history(node, métrique, début, fin)` | backend, à la demande | Une courbe. Vide par défaut (iTop, par exemple, ne mesure rien). |

La classe de base fournit le client HTTP, la mesure de latence et un
**disjoncteur** : après 3 échecs consécutifs, l'outil n'est plus sollicité
pendant 60 secondes, pour ne pas s'acharner sur un outil déjà en difficulté.

## Le vocabulaire commun

Chaque outil a ses propres codes. Les connecteurs les traduisent vers un
vocabulaire unique défini dans `integrations/models.py` et
`integrations/normalize.py`.

**Gravités** : `critical`, `high`, `medium`, `low`, `info`, `unknown`.

| Outil | Valeur brute → gravité |
|---|---|
| Zabbix (0–5) | 5 → critical, 4 → high, 3 → medium, 2 → low, 1 → info, 0 → unknown |
| Centreon service | CRITICAL → critical, WARNING → medium, UNKNOWN → unknown |
| Centreon hôte | DOWN → critical, UNREACHABLE → high |
| iTop (priorité) | 1 → critical, 2 → high, 3 → medium, 4 → low |
| NetXMS (0–4) | 4 → critical, 3 → high, 2 → medium, 1 → low, 0 → info |
| Nagios, NSP | libellés textuels (critical, major, minor, warning…) |

Une valeur inconnue devient `unknown`, jamais `info` : une alerte dont on n'a
pas su lire la gravité ne doit pas disparaître de l'écran.

**États d'équipement** : `down` (hors service), `degraded` (dégradé),
`silent` (muet : l'outil ne dit plus rien), `maintenance`, `up` (nominal),
`unknown`.

## Les connecteurs, un par un

### Zabbix 7.0 — `integrations/zabbix.py`

- **API** : JSON-RPC sur `/api_jsonrpc.php`.
- **Authentification** : jeton d'API permanent (`ZABBIX_API_TOKEN`, préféré)
  ou identifiant/mot de passe.
- **Alertes** : `problem.get` (seulement les problèmes actifs).
- **Historique** : `history.get` pour les valeurs brutes récentes,
  `trend.get` au-delà (moyennes horaires).
- **Site** : déduit des groupes d'hôtes nommés `Site/<nom>` ou
  `Localité/<nom>` — convention à respecter côté Zabbix.

### Centreon 22.10 — `integrations/centreon.py`

- **API** : REST v2 sous `/centreon/api/latest`, endpoint unifié
  `/monitoring/resources` (hôtes et services en un appel).
- **Authentification** : jeton de session, renouvelé automatiquement dès qu'un
  appel répond 401.

### iTop 3.2 — `integrations/itop.py`

- **API** : REST/JSON sur `/webservices/rest.php`.
- **Rôle** : CMDB (organisation, responsable, emplacement des équipements) et
  tickets (`ITOP_TICKET_CLASSES`, par défaut `Incident,UserRequest`). Ne
  mesure rien.
- **Priorité dans la fusion** : iTop fait foi pour le **nom**, le **site** et
  l'**organisation** d'un équipement.
- **Compte de service** : il lui faut plusieurs profils iTop, pas seulement
  « REST Services User » (voir [tools/README.md](../tools/README.md)).

### NetXMS 5.0 — deux connecteurs, un seul réglage

NetXMS peut être lu de **deux façons**, et le choix se fait par la **forme de
l'URL** dans `NETXMS_API_URL` (`integrations/config.py`) :

| URL | Connecteur | Quand l'utiliser |
|---|---|---|
| `https://…` | `netxms.py` — API Web (`netxms-websvc`) | L'agence fournit un compte NetXMS |
| `postgresql://…` | `netxms_db.py` — base PostgreSQL, **lecture seule** | L'agence fournit un compte de lecture sur la base, ou en local avec le dump |

Les deux produisent exactement les mêmes équipements et alertes : passer de
l'un à l'autre ne change que cette variable.

Particularités du connecteur base (`netxms_db.py`) :

- **Site** : issu du référentiel de sites propre à l'agence
  (`object_properties.siteadmin_id` → `donnebase.siteadministratif`), avec
  repli sur la ville de l'objet. La présence du référentiel est détectée : le
  connecteur fonctionne aussi sur une base NetXMS standard.
- **Alarmes d'interface** : rattachées à leur équipement via `interfaces.node_id`.
- **Garanties** : chaque connexion est ouverte en lecture seule, avec un délai
  de garde ; aucune colonne secrète (communautés SNMP, secrets d'agent) n'est
  lue.
- **Historique** : non disponible (les mesures sont dans des hypertables
  TimescaleDB, absentes d'un dump).

### Nagios et Nokia NSP — `nagios.py`, `nsp.py`

Écrits, jamais testés sur une instance réelle (aucune n'est disponible en
local). Chacun a plusieurs modes d'accès à confirmer auprès de l'agence :
`NAGIOS_MODE` (`statusjson`, `livestatus`, `xi`) et `NSP_FM_MODE` (`yang`,
`classic`). Tant qu'ils valent `unknown`, le connecteur se déclare « non
configuré » en nommant la variable à renseigner.

## La fusion des équipements

Un même routeur peut être connu de Zabbix, de NetXMS et d'iTop sous trois noms
différents. Le collecteur les rapproche (`collector/merge.py`) **uniquement sur
des preuves** :

1. **Même adresse IP** — preuve (les adresses de bouclage et `0.0.0.0` sont
   ignorées) ;
2. **Même nom technique après normalisation** — minuscules, domaine retiré,
   séparateurs unifiés. Une adresse IP écrite à la place d'un nom n'est
   **jamais** comparée comme un nom ;
3. **rien d'autre** : aucune ressemblance approximative. Fusionner deux
   équipements différents ferait disparaître un site entier de la supervision.

Deux objets d'un **même** outil ne sont jamais fusionnés : pour cet outil, ce
sont deux équipements distincts.

Quand les outils ne sont pas d'accord :

| Champ | Qui l'emporte |
|---|---|
| État (hors service, nominal…) | Zabbix, puis Centreon, NetXMS, Nagios, NSP — un outil qui **mesure** |
| Nom, site, organisation | iTop, puis Zabbix, Centreon, NetXMS… — un outil de **référence** |

Le résultat du rapprochement (combien par IP, combien par nom, équipements vus
par un seul outil) est affiché sur l'écran **Collecte ETL** : l'exploitant peut
contrôler ce que la machine a décidé.

## Les trois façons d'alimenter la plateforme en local

| Mode | Réalisme | Mise en place |
|---|---|---|
| **Dump NetXMS** | Données réelles de production, figées au 07/08/2026 | [README § 3.1](../README.md#31-base-netxms-restaurée-depuis-le-dump) |
| **Outils de laboratoire** | Vrais Zabbix/iTop/Centreon aux versions de l'agence, supervisant les conteneurs de la pile. Une vraie panne (arrêter un conteneur) produit une vraie alerte. | [README § 3.2](../README.md#32-outils-de-laboratoire-zabbix-itop-centreon), [tools/README.md](../tools/README.md) |
| **Outils de l'agence** | Le réseau réel, en direct | [README § 3.3](../README.md#33-outils-réels-de-lagence) |

### Le dump NetXMS en détail

`database/netxmsbd07082026.sql` est une copie de la base du serveur NetXMS de
production (PostgreSQL 16, avec PostGIS et les schémas propres à l'agence :
`donnebase` pour le référentiel géographique et administratif,
`equipementinfastructure` pour les sites techniques et pylônes).

Le script `database/restore_netxms_dump.sh` :

1. crée les rôles de production cités par le dump (sans mot de passe, pour que
   les droits se restaurent) ;
2. installe PostGIS et retire les déclencheurs TimescaleDB ;
3. restaure le dump (≈ 4 minutes) ;
4. **purge les secrets** (`netxms_sanitize.sql`) : communautés SNMP, mots de
   passe SNMPv3, empreintes de mots de passe des comptes NetXMS, jetons des
   canaux de notification, coordonnées personnelles ;
5. crée le compte **`noc_reader`** (`netxms_readonly_role.sql`) : lecture
   seule, sur les seules colonnes utiles, trois connexions au maximum.

Deux règles de sécurité :

- **Aucun serveur NetXMS n'est démarré sur ce dump.** Il reprendrait la
  configuration de production et enverrait courriels et messages Telegram à de
  vraies personnes.
- **Le dump reste hors de git** et la base n'est accessible que depuis le poste
  (`127.0.0.1:5438`).

## Garanties envers la production

À présenter à l'équipe sécurité de l'agence :

| Garantie | Comment elle est tenue |
|---|---|
| **Charge constante et connue** | Une série de requêtes par outil toutes les `COLLECT_INTERVAL_S` secondes (300 par défaut), quel que soit le nombre d'utilisateurs connectés. Les courbes à la demande sont mises en cache. |
| **Lecture seule** | Aucun connecteur n'écrit chez un outil. Pour NetXMS par la base, le compte `noc_reader` est en lecture seule **imposée par le serveur**. |
| **Droits minimaux** | `netxms_readonly_role.sql` n'accorde que les colonnes lues, jamais les secrets. Pour Zabbix : un jeton d'API révocable ; pour iTop : un compte de service dédié. |
| **Pas de copie des données** | Rien n'est recopié en base ; l'état courant expire de lui-même en 15 minutes si la collecte s'arrête. |
| **Robustesse** | Délais de garde, disjoncteur, cycle borné : un outil lent ne peut pas être submergé par le NOC. |

## Ajouter un nouvel outil

1. Créer `integrations/<outil>.py`, classe héritant de `SourceClient`, avec
   `check`, `fetch_nodes`, `fetch_alerts` (et `fetch_history` si l'outil a des
   mesures).
2. Ajouter la table de traduction de ses gravités dans `normalize.py`.
3. Ajouter une branche dans `build_client()` et le nom dans `TOOL_NAMES`
   (`integrations/config.py`).
4. Ajouter ses priorités dans `STATE_PRIORITY` et `REFERENCE_PRIORITY`
   (`collector/merge.py`).
5. Déclarer `<OUTIL>_API_URL`, `_USER`, `_PASSWORD` dans `docker-compose.yml`
   (services `collector` **et** `backend`) et dans `.env.example`.
6. Ajouter son libellé dans `frontend/src/lib/vocabulary.js` (`TOOL_LABEL`) et
   son nom dans `SUPERVISION_TOOLS`.
7. Reconstruire : `docker compose up -d --build collector backend frontend`.

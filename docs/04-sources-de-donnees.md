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
| Zabbix (0–5) | 5 → critical, 4 → high, 3 → medium, 2 → medium, 1 → info, 0 → unknown |
| Centreon service | CRITICAL → critical, WARNING → medium, UNKNOWN → unknown |
| Centreon hôte | DOWN → critical, UNREACHABLE → high |
| iTop (priorité) | 1 → critical, 2 → high, 3 → medium, 4 → low |
| NetXMS (0–4) | 4 → critical, 3 → high, 2 → medium, 1 → medium, 0 → info |
| Nagios, NSP | libellés textuels (critical, major, minor, warning…) |

Une valeur inconnue devient `unknown`, jamais `info` : une alerte dont on n'a
pas su lire la gravité ne doit pas disparaître de l'écran.
`WARNING` est normalisé à `medium` dans Zabbix, Centreon et NetXMS : un seuil
à examiner ne doit pas être assimilé à une panne critique.

**États d'équipement** : `down` (hors service), `degraded` (dégradé),
`silent` (muet : l'outil ne dit plus rien), `maintenance`, `up` (nominal),
`unknown`.

## Les connecteurs, un par un

### Zabbix 7.0 — `integrations/zabbix.py`

- **API** : JSON-RPC sur `/api_jsonrpc.php`.
- **Authentification** : jeton d'API permanent (`ZABBIX_API_TOKEN`, préféré)
  ou identifiant/mot de passe.
- **Alertes** : `problem.get` (seulement les problèmes actifs).
- **Limites explicites** : si l'API atteint 5 000 problèmes ou points
  historiques, la collecte signale un résultat potentiellement tronqué au
  lieu de le présenter comme complet.
- **Historique** : `history.get` pour les valeurs brutes récentes,
  `trend.get` au-delà (moyennes horaires).
- **Disques** : seules les clés `vfs.fs.size` en mode `pused` ou `pfree` sont
  converties en pourcentage utilisé; `pfree` est inversé. Les valeurs en
  octets ne sont pas présentées comme un pourcentage.
- **Site** : déduit des groupes d'hôtes nommés `Site/<nom>` ou
  `Localité/<nom>` — convention à respecter côté Zabbix.

### Centreon 22.10 — `integrations/centreon.py`

- **API** : REST v2 sous `/centreon/api/latest`, endpoint
  `/monitoring/resources`. L'inventaire ne retient que les hôtes; les
  services sont des contrôles, rattachés à leur hôte dans les alertes.
- **Authentification** : jeton de session, renouvelé automatiquement dès qu'un
  appel répond 401.
- **Limites explicites** : la pagination est suivie jusqu'au total annoncé;
  au-delà de 20 000 ressources, la collecte échoue visiblement plutôt que de
  publier un inventaire tronqué.

### iTop 3.2 — `integrations/itop.py`

- **API** : REST/JSON sur `/webservices/rest.php`.
- **Rôle** : CMDB (organisation, responsable, emplacement des équipements) et
  tickets (`ITOP_TICKET_CLASSES`, par défaut `Incident,UserRequest`). Les
  tickets sont classés comme `itsm_ticket` et ne sont pas comptés comme des
  alertes techniques ni diffusés comme de nouvelles alertes. iTop ne mesure
  rien. La supervision et son bandeau n'affichent que les alertes techniques;
  la page Incidents permet de filtrer les alertes techniques, tickets iTop et
  incidents manuels par catégorie.
- **Priorité dans la fusion** : iTop fait foi pour le **nom**, le **site** et
  l'**organisation** d'un équipement.
- **Compte de service** : il lui faut plusieurs profils iTop, pas seulement
  « REST Services User » (voir [tools/README.md](../tools/README.md)).
- **Classes optionnelles** : les classes absentes selon les modules activés
  sont omises mais signalées dans la santé de l'intégration. Les autres
  erreurs d'accès ne sont pas converties en inventaires ou tickets vides.
- **SLT** : une erreur de lecture des objectifs remonte au consommateur au
  lieu d'être convertie en liste vide. Les indicateurs SLA ne doivent pas
  présenter ces objectifs comme récupérés. La lecture des objectifs n'est
  pas encore reliée au calcul SLA du backend; celui-ci ne consomme donc pas
  les objectifs iTop.
- **Rattachement** : les identifiants numériques iTop sont utilisés pour
  faire correspondre `id` et `functionalci_id`, pas les clés OQL `Classe::id`.

### NetXMS 5.0 — deux connecteurs, un seul réglage

NetXMS peut être lu de **deux façons**, et le choix se fait par la **forme de
l'URL** dans `NETXMS_API_URL` (`integrations/config.py`) :

| URL | Connecteur | Quand l'utiliser |
|---|---|---|
| `https://…` | `netxms.py` — API Web (`netxms-websvc`) | Après validation des endpoints sur la version déployée |
| `postgresql://…` | `netxms_db.py` — base PostgreSQL, **lecture seule** | Préféré si l'agence accorde un compte dédié en lecture seule |

Les deux produisent exactement les mêmes équipements et alertes : passer de
l'un à l'autre ne change que cette variable.

Le connecteur API emploie des endpoints de la Legacy Web API dont le
comportement n'a pas été confirmé sur l'instance de production. Quand l'accès
à la base est accordé, le compte `noc_reader` et les requêtes en lecture
seule de `netxms_db.py` sont donc le chemin de production recommandé. Ne
basculer sur l'API qu'après validation de `/objects`, `/alarms` et des DCI
sur la version réellement exploitée.

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

Nagios est validé sur le laboratoire local (Nagios Core 4.5.12, profil
`nagios`, mode `statusjson`). Attention aux codes d'état : les CGI JSON
emploient des masques de bits (hôte 2 UP, 4 DOWN, 8 UNREACHABLE ; service
2 OK, 4 WARNING, 8 UNKNOWN, 16 CRITICAL), pas les codes de retour des sondes.
`objectjson.cgi` plante sur un alias accentué : le connecteur publie alors
l'état sans adresses ni groupes et le signale. NSP n'a pas d'instance locale.
Chacun a plusieurs modes d'accès à confirmer auprès de l'agence :
`NAGIOS_MODE` (`statusjson`, `livestatus`, `xi`) et `NSP_FM_MODE` (`yang`,
`classic`). Tant qu'ils valent `unknown`, le connecteur se déclare « non
configuré » en nommant la variable à renseigner.

Nagios XI n'est pas encore implémenté : le mode `xi` renvoie une erreur
explicite et ne se déclare pas sain avec des listes vides. Les modes
`statusjson` et `livestatus` restent distincts.
Le mode NSP `classic` ne fournit pas d'inventaire; cette couverture partielle
est signalée dans l'état de l'intégration, même si ses alarmes sont collectées.

## Alertes et incidents : deux choses différentes

- Une **alerte** est un signal technique d'un outil de supervision (Zabbix,
  Centreon, NetXMS, Nagios, NSP). Écran « Alertes outils ».
- Un **incident** est un ticket **iTop**, et seulement iTop (classes
  `ITOP_TICKET_CLASSES`). Écran « Incidents iTop ». Le NOC ne fabrique pas
  d'incident à partir d'une alerte ; la fiche d'un incident montre, à côté du
  ticket, l'état de l'équipement concerné vu par chaque outil et ses alertes
  en cours (rattachement par référence, puis par nom technique quand le CI
  iTop n'a pas d'IP commune avec l'hôte supervisé).
- Les **SLA** se mesurent sur les incidents iTop : délai de prise en charge
  (assignation − ouverture) et de résolution (résolution − ouverture),
  comparés aux objectifs par gravité. Les tickets résolus restent chez iTop
  et y sont lus à la demande (`fetch_incident_history`, cache de 5 min). Un
  incident ouvert qui a déjà dépassé son objectif compte comme non tenu.
- iTop enregistre ses dates dans le fuseau de sa configuration
  (`timezone` de `config-itop.php`, « Europe/Paris » par défaut) :
  `ITOP_TIMEZONE` doit lui être identique, sinon tous les délais sont décalés.

## Région, province, site, nœud

Chaque équipement porte son site, sa province et sa région (17 régions du
nouveau découpage), lus chez les sources et jamais devinés :

- **NetXMS (base)** : référentiel de l'agence, site administratif → ville →
  commune → province → région ; à défaut de site, la ville de l'objet quand
  elle ne désigne qu'une seule province. Le compte `noc_reader` doit avoir les
  droits du bloc « Découpage administratif » de
  `database/netxms_readonly_role.sql`.
- **Zabbix, Centreon, Nagios** : groupes d'hôtes `Site/…`, `Province/…`,
  `Region/…` (ou `Région/…`).
- **Héritage** : un équipement dont seul le site est connu hérite de la
  province et de la région d'un autre équipement du même site, si ce site
  n'est rattaché qu'à une seule province.

Les équipements sans localité sont comptés sous « Région non renseignée »,
visibles et classés en dernier. Toutes les routes de lecture acceptent le même
périmètre (`region`, `province`, `site`, `search`), appliqué par
`backend/app/services/geo_service.py` ; l'écran Territoire désagrège du pays
jusqu'au nœud, et la position d'un site est le barycentre de ses équipements
situés.

## Interpréter les agrégats

- La disponibilité instantanée et les agrégats journaliers excluent les
  équipements en maintenance planifiée du dénominateur. Un état inconnu,
  muet, dégradé ou en panne n'est jamais assimilé à « disponible ».
- Une courbe réseau interroge un échantillon stable, sélectionné par hachage
  de l'identifiant, de la métrique et de la période, plafonné à 50 équipements
  par requête. La réponse et l'écran indiquent la taille du parc, la taille de
  l'échantillon, les équipements contributeurs et les erreurs rencontrées :
  cette moyenne n'est pas présentée comme une mesure exhaustive.
- Pour ne pas surpondérer une sonde qui publie plus souvent, chaque
  équipement est d'abord moyenné par minute, puis les moyennes des
  équipements sont agrégées. Chaque point précise combien d'équipements ont
  contribué à cette minute; les horodatages sont conservés en UTC.
- Les agrégats journaliers excluent les fenêtres de maintenance planifiée. Si
  la lecture des fenêtres échoue ou dépasse son délai, le collecteur omet
  l'échantillon KPI et journalise le problème plutôt que de supposer qu'aucune
  maintenance n'existe. Cette règle s'applique aux nouveaux échantillons ; les
  agrégats historiques ne sont pas recalculés rétroactivement.

## La fusion des équipements

L'identifiant source reste toujours le couple `(outil, référence)`. En
l'absence d'une correspondance CMDB validée, le collecteur fusionne
automatiquement uniquement si le nom technique complet (casse ignorée, point
DNS final retiré) **et** l'adresse IP normalisée sont identiques entre outils,
et que cette identité n'apparaît qu'une fois par outil. Il ne retire pas les
suffixes DNS et ne fusionne ni sur l'IP seule ni sur le nom seul. Les collisions
et équipements aux informations incomplètes restent séparés et sont exposés
dans le rapport d'interopérabilité.

Les états techniques ne suivent pas de priorité d'outil arbitraire : iTop
n'est pas une source de mesure. Si plusieurs sources supervisant un même
équipement fournissent des états différents, l'état consolidé devient
`unknown` et les états de chaque source sont rendus dans `state_conflicts`.
Le nom, le site et l'organisation restent du contexte CMDB priorisé depuis
iTop, puis les sources de supervision.

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
| **Pas de copie brute des données** | L'inventaire et les alertes courantes résident dans l'instantané Redis, qui expire après trois cycles si la collecte s'arrête. PostgreSQL conserve les opérations du NOC et des agrégats KPI journaliers, pas une copie des données brutes des outils. |
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

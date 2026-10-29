# 4. Sources de données

La plateforme ne crée aucune donnée de supervision : elle la lit chez les
**outils sources** grâce à des **connecteurs** (`integrations/`). En
production, **uniquement par leurs API** ; les exports de production (dump
NetXMS, journal Centreon) ne servent qu'à visualiser en local.

## Le contrat d'un connecteur

Chaque connecteur hérite de `SourceClient` (`integrations/base.py`) et
implémente quatre méthodes :

| Méthode | Appelée par | Rôle |
|---|---|---|
| `check()` | collecteur, à chaque cycle | L'outil répond-il ? En combien de temps ? Quelle version ? Ne lève jamais : une panne se raconte par un `ToolHealth(reachable=False, error=…)`. |
| `fetch_nodes()` | collecteur | L'inventaire des équipements (`list[Node]`) |
| `fetch_alerts()` | collecteur | Les alertes **actives uniquement** (`list[Alert]`) |
| `fetch_history(node, métrique, début, fin)` | backend, à la demande | Une courbe. Vide par défaut (iTop, par exemple, ne mesure rien). |

Méthodes facultatives, vides par défaut :

| Méthode | Appelée par | Rôle | Implémentée par |
|---|---|---|---|
| `fetch_fleet_latest()` | collecteur | Dernière valeur de chaque mesure pour tout le parc, en un appel groupé | Zabbix |
| `fetch_latest(node)` | backend | Dernières valeurs d'un équipement | Zabbix |
| `fetch_maintenance()` | collecteur | Maintenances planifiées | iTop (changements), Zabbix |
| `fetch_work_orders()` | collecteur | Ordres de travail | iTop |
| `fetch_incident_history(début, fin)`, `fetch_sla_targets()` | backend, à la demande | Tickets de la période, engagements contractuels | iTop |

Un équipement peut porter des **faits de fiche** (`Node.details`) : inventaire
matériel, dernier démarrage, heure de la panne, disponibilité calculée par
l'agence, résumé des interfaces. Une alerte peut porter son **contexte**
(`Alert.details`) : tags, donnée opérationnelle, commentaires… Ces champs
sont affichés sur les fiches, jamais utilisés pour décider d'un état ou d'un
décompte.

`python -m collector.probe [outil]` exécute un cycle de lecture contre l'outil
réel, sans rien publier, et dit ce qui est lu et ce qui manque (équipements
localisés, alertes rattachées, champs reçus).

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
- **Alertes** : `problem.get` (seulement les problèmes actifs), avec leurs
  **tags**, leur **donnée opérationnelle** (« 95 % utilisé »), l'indicateur
  de **suppression** par une maintenance, le lien **cause → symptôme**
  (Zabbix 7, `cause_eventid`) et les **commentaires d'acquittement** — affichés
  sur la fiche d'alerte, jamais utilisés pour les décomptes.
- **Inventaire** : constructeur, modèle, n° de série, système, type et
  emplacement de l'inventaire d'hôte, sur la fiche d'équipement. Aucun champ
  de contact n'est demandé (données personnelles).
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
- **Export du journal, en local** : `CENTREON_API_URL=file:///…` remplace
  l'API par `centreon_logs.py`, qui rejoue un export de
  `centreon_storage.logs` (README § 3.2). Mêmes références (`host-<id>`,
  `service-<id>`) et mêmes états que l'API. Seuls les états HARD font une
  alerte, datée du premier état HARD de la série ; un acquittement ne survit
  pas à un changement d'état. Un hôte sans ligne de contrôle d'hôte (Centreon
  ne journalise que les changements) prend l'état de ses services : tous
  nominaux, en service ; l'un en alerte, dégradé. Ni groupes, ni localité, ni
  mesures.

### iTop 3.2 — `integrations/itop.py`

- **API** : REST/JSON sur `/webservices/rest.php`.
- **Rôle** : CMDB (organisation, responsable, emplacement des équipements) et
  tickets (`ITOP_TICKET_CLASSES`, par défaut `Incident,UserRequest`). Les
  tickets sont classés comme `itsm_ticket` et ne sont pas comptés comme des
  alertes techniques ni diffusés comme de nouvelles alertes. iTop ne mesure
  rien. Les tickets ouverts sont dans l'instantané ; les tickets clos sont lus
  à la demande (`fetch_incident_history`, cache de 5 min).
- **Priorité dans la fusion** : iTop fait foi pour le **nom**, le **site** et
  l'**organisation** d'un équipement.
- **Compte de service** : il lui faut plusieurs profils iTop, pas seulement
  « REST Services User » (voir [tools/README.md](../tools/README.md)).
- **Classes optionnelles** : les classes absentes selon les modules activés
  sont omises mais signalées dans la santé de l'intégration. Les autres
  erreurs d'accès ne sont pas converties en inventaires ou tickets vides.
- **SLT** : les engagements contractuels sont lus à la demande
  (`GET /api/sla/contract`, cache de 5 min) et affichés sur l'écran SLA à
  côté des objectifs du NOC, en minutes, le plus exigeant par gravité. Ils ne
  remplacent pas les objectifs du NOC : un écart se voit et se corrige à la
  main. Une instance sans classe SLT est signalée comme telle ; toute autre
  erreur remonte au lieu d'être convertie en liste vide.
- **Événement Zabbix** (`ITOP_ZBX_EVENT_FIELD`) : la fiche d'incident nomme
  le problème Zabbix à l'origine du ticket et le repère parmi les alertes.
- **Rattachement** : les identifiants numériques iTop sont utilisés pour
  faire correspondre `id` et `functionalci_id`, pas les clés OQL `Classe::id`.

### NetXMS 5.0 — deux connecteurs, un seul réglage

NetXMS peut être lu de **deux façons**, et le choix se fait par la **forme de
l'URL** dans `NETXMS_API_URL` (`integrations/config.py`) :

| URL | Connecteur | Usage |
|---|---|---|
| `https://…` | `netxms.py` — API Web (`netxms-websvc`) | **Production** : en exploitation, toutes les données viennent des API |
| `postgresql://…` | `netxms_db.py` — base PostgreSQL, **lecture seule** | **Local** : visualiser le dump de production restauré |

Les deux produisent les mêmes équipements et alertes : passer de l'un à
l'autre ne change que cette variable.

Particularités du connecteur API (`netxms.py`) :

- **À valider sur l'instance réelle** : les chemins (`/objects`, `/alarms`,
  DCI) et la forme des réponses n'ont pas été confrontés à l'instance de
  l'agence. Le connecteur accepte les variantes connues (classe, état et
  gravité en nombre ou en nom ; dates en secondes, millisecondes ou ISO 8601).
  `python -m collector.probe netxms` dit ce qui est lu et ce qui manque.
- **Localité** : l'API ne donne pas le référentiel de sites de l'agence
  (propre à sa base). Le **site** est l'attribut personnalisé désigné par
  `NETXMS_SITE_ATTRIBUTE`, sinon la ville de l'adresse NetXMS. La **province
  et la région** viennent de cette ville, sinon des coordonnées placées dans
  le contour de leur région (`integrations/localities.py`, référentiel figé
  dans `integrations/data/localities.json` par
  `database/export_localities.py`). Mesuré sur le dump : région trouvée pour
  85 % des équipements, province pour 70 % (80 % des équipements ont un site
  administratif en mode base). Pour retrouver ce niveau, l'agence peut
  recopier le site administratif dans un attribut personnalisé des nœuds.
- **Alarmes d'interface** : leur objet source est une interface ; son
  équipement est lu une fois (`/objects/{id}`, au plus 100 par cycle), puis
  gardé en mémoire.
- **Groupes** : noms des conteneurs NetXMS ; s'ils ne sont pas lisibles,
  l'inventaire est publié sans groupes.
- **Fiche d'équipement** : constructeur, modèle, n° de série, dernier
  démarrage, heure de la panne ; disponibilité calculée par l'agence
  (attributs personnalisés `perAvailability`, `mttr`, `mtbf`, `NumFailures`
  — 72 nœuds dans le dump) ; résumé des **interfaces** (activées, actives,
  surveillées, débit nominal), qui donne la disponibilité des liens. Les
  interfaces sont la lecture la plus lourde : `NETXMS_COLLECT_INTERFACES=false`
  la coupe.

Particularités du connecteur base (`netxms_db.py`) :

- **Site** : issu du référentiel de sites propre à l'agence
  (`object_properties.siteadmin_id` → `donnebase.siteadministratif`), avec
  repli sur la ville de l'objet. La présence du référentiel est détectée : le
  connecteur fonctionne aussi sur une base NetXMS standard.
- **Alarmes d'interface** : rattachées à leur équipement via `interfaces.node_id`.
- **Fiche d'équipement** : mêmes faits que par l'API, lus seulement si
  `noc_reader` a les droits du bloc « Fiche d'équipement » de
  `netxms_readonly_role.sql` ; les attributs personnalisés passent par la vue
  `noc_availability_attributes`, limitée aux attributs de disponibilité.
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
l'état sans adresses ni groupes et le signale. NSP n'a pas d'instance locale :
un **simulateur** (`tools/nsp-sim`, profil `nsp`) répond aux requêtes du
connecteur pour voir des données NSP dans le NOC, sans prouver la
compatibilité avec le NSP de l'agence (tools/README.md).
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

- **NetXMS (API, production)** : site = attribut personnalisé
  (`NETXMS_SITE_ATTRIBUTE`) ou ville de l'adresse NetXMS ; province et région
  d'après la ville, sinon d'après les coordonnées
  (`integrations/localities.py`).
- **NetXMS (base, dump local)** : référentiel de l'agence, site administratif
  → ville → commune → province → région ; à défaut de site, la ville de
  l'objet quand elle ne désigne qu'une seule province. Le compte `noc_reader`
  doit avoir les droits du bloc « Découpage administratif » de
  `database/netxms_readonly_role.sql`.
- **Centreon (export du journal)** : aucune localité, le journal n'a pas les
  groupes d'hôtes.
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

## Les façons d'alimenter la plateforme en local

| Mode | Réalisme | Mise en place |
|---|---|---|
| **Dump NetXMS** | Données réelles de production, figées au 07/08/2026 — visualisation locale uniquement, jamais en production | [README § 3.1](../README.md#31-base-netxms-restaurée-depuis-le-dump) |
| **Journal Centreon** | Export de `centreon_storage.logs`, 25/09 → 27/10/2026 — visualisation locale uniquement | [README § 3.2](../README.md#32-export-du-journal-centreon) |
| **Outils de laboratoire** | Vrais Zabbix/iTop/Centreon aux versions de l'agence, supervisant les conteneurs de la pile. Une vraie panne (arrêter un conteneur) produit une vraie alerte. | [README § 3.3](../README.md#33-outils-de-laboratoire), [tools/README.md](../tools/README.md) |
| **Outils de l'agence** | Le réseau réel, en direct | [README § 3.4](../README.md#34-outils-réels-de-lagence) |

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

Après une mise à jour de `netxms_readonly_role.sql` (nouveaux droits pour la
fiche d'équipement), le rejouer sur une base déjà restaurée :

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms   -v reader_password="<NETXMS_DB_READER_PASSWORD>" -f - < database/netxms_readonly_role.sql
```

### Le journal Centreon en détail

`database/alertes.sql` est un export **tabulé** de la table
`centreon_storage.logs` (et non un dump SQL) : 47 132 événements de 12 hôtes
ANPTIC, du 25/09 au 27/10/2026. `integrations/centreon_logs.py` le rejoue
dans l'ordre pour reconstituer le dernier état de chaque hôte et de chaque
service ; le collecteur le lit par `docker-compose.dumps.yml` (lecture seule).
L'export fourni ne contient que des états OK : il donne 12 hôtes en service et
aucune alerte. Il est exclu de git.

## Garanties envers la production

À présenter à l'équipe sécurité de l'agence :

| Garantie | Comment elle est tenue |
|---|---|
| **Charge constante et connue** | Une série de requêtes par outil toutes les `COLLECT_INTERVAL_S` secondes (300 par défaut), quel que soit le nombre d'utilisateurs connectés. Les courbes à la demande sont mises en cache. |
| **Lecture seule** | Aucun connecteur n'écrit chez un outil : comptes en lecture sur les API (NetXMS, Centreon, Nagios, NSP), jeton d'API révocable pour Zabbix, compte de service dédié pour iTop. |
| **Droits minimaux** | Les comptes ne demandent que la lecture des objets supervisés et des alertes ; aucun champ de contact Zabbix n'est lu. |
| **Pas de copie brute des données** | L'inventaire et les alertes courantes résident dans l'instantané Redis, qui expire après trois cycles si la collecte s'arrête. PostgreSQL conserve les comptes, les objectifs SLA, le journal d'audit et des agrégats journaliers, pas une copie des données des outils. |
| **Robustesse** | Délais de garde, disjoncteur, cycle borné : un outil lent ne peut pas être submergé par le NOC. |

## Ajouter un nouvel outil

1. Créer `integrations/<outil>.py`, classe héritant de `SourceClient`, avec
   `check`, `fetch_nodes`, `fetch_alerts` (et `fetch_history` si l'outil a des
   mesures).
2. Ajouter la table de traduction de ses gravités dans `normalize.py`.
3. Ajouter une branche dans `build_client()` et le nom dans `TOOL_NAMES`
   (`integrations/config.py`).
4. Ajouter son nom dans `REFERENCE_PRIORITY` (`collector/merge.py`) : ordre
   de préférence pour le nom, le site et l'organisation d'un équipement.
5. Déclarer `<OUTIL>_API_URL`, `_USER`, `_PASSWORD` dans `docker-compose.yml`
   (services `collector` **et** `backend`) et dans `.env.example`.
6. Ajouter son libellé dans `frontend/src/lib/vocabulary.js` (`TOOL_LABEL`).
7. Vérifier contre l'instance réelle : `python -m collector.probe <outil>`.
8. Reconstruire : `docker compose up -d --build collector backend frontend`.

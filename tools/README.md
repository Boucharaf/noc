# Instances locales des outils sources

Ce répertoire monte, sur le poste de développement, les **mêmes versions**
d'outils que celles exploitées en production par l'agence :

| Outil | Version | Interface | API interrogée par le collecteur |
|---|---|---|---|
| Zabbix | **7.0.23** | <http://localhost:8081> — `Admin` / `zabbix` | `http://zabbix-web:8080/api_jsonrpc.php` |
| Centreon | **22.10.7** — ⚠️ non constructible, voir plus bas | <http://localhost:8084/centreon> — `admin` | `http://centreon/centreon/api/latest` |
| iTop | **3.2.3-2** (build 20678) | <http://localhost:8082> — `admin` | `http://itop/webservices/rest.php` |
| Nagios Core | **4.5.12** | <http://localhost:8085/nagios> — `nagiosadmin` / `NAGIOS_API_PASSWORD` | `http://nagios/nagios/cgi-bin/statusjson.cgi` |

## Pourquoi à l'identique

Une intégration validée contre Zabbix 7.2 ne prouve rien sur du 7.0. D'une
version mineure à l'autre changent le mode d'authentification du JSON-RPC,
le nom des champs de `host.get`, la forme des réponses. Ces conteneurs
existent pour que « ça marche en local » soit une **garantie** et non une
impression — et pour que l'agence n'ait pas à ouvrir ses accès de
production pour valider l'intégration.

## Démarrer

Les outils ne démarrent pas avec `docker compose up` : ils pèsent plusieurs
gigaoctets et un poste de 8 Go ne les tient pas tous confortablement en même
temps que la plateforme. Ils se lancent par profil :

```bash
docker compose --profile zabbix   up -d     # ~0,3 Go (allégé, voir plus bas)
docker compose --profile netlab   up -d     # ~0,1 Go — 6 équipements réseau
docker compose --profile itop     up -d     # ~0,8 Go
docker compose --profile centreon up -d     # ~2,0 Go
docker compose --profile nagios   up -d     # ~0,2 Go
docker compose --profile tools    up -d     # zabbix + centreon + itop + nagios
docker compose --profile netxms   up -d netxms-db   # base du dump NetXMS (voir plus bas)
```

Sur une machine de 8 Go, le mode d'emploi réaliste est : Zabbix, iTop et
Nagios ensemble, Centreon séparément.

**Premier démarrage.** Centreon et iTop s'installent tout seuls et cela
prend quelques minutes ; les conteneurs ne sont déclarés sains qu'une fois
leur API capable de répondre à une authentification — pas avant. Suivre :

```bash
docker compose logs -f centreon itop
```

## Le réseau de laboratoire (`netdevice/`, profil `netlab`)

Sans équipement réseau à superviser, Zabbix ne remonte ni interface, ni
débit, ni latence : les panneaux réseau du NOC restent vides. Le profil
`netlab` démarre six « équipements » de site, chacun un conteneur Alpine
d'environ 16 Mo :

| Équipement | Région / province | Lien simulé |
|---|---|---|
| `LAB-OUAGA-CORE-RT01` | Kadiogo / Kadiogo | cœur, ~1 ms, reçoit le trafic des sites |
| `LAB-OUAGA-DIST-SW01` | Kadiogo / Kadiogo | distribution, ~1 ms |
| `LAB-BOBO-RT01` | Guiriko / Houet | fibre, ~22 ms |
| `LAB-MANGA-RT01` | Nazinon / Zoundweogo | faisceau hertzien, ~45 ms ± 15, 2 % de pertes |
| `LAB-OUAHIGOUYA-VSAT01` | Yaadga / Yatenga | satellite, ~380 ms, 6 % de pertes |
| `LAB-DEDOUGOU-RT01` | Bankui / Mouhoun | instable : coupé 6 min toutes les 30 |

Chacun porte un **vrai agent SNMP** (net-snmp : interfaces 64 bits, CPU,
mémoire, disque), envoie un **vrai trafic** à un voisin (variable selon
l'heure) et applique les conditions de son lien. Zabbix les supervise avec
le gabarit livré **« Linux by SNMP »** (interfaces, débits, CPU, mémoire,
ICMP) ; ses déclencheurs standard produisent de vraies alertes (temps de
réponse élevé sur le VSAT, équipement injoignable pendant les coupures de
Dédougou), qui remontent au NOC.

**Pourquoi pas `tc netem`.** Le noyau WSL2 de Docker Desktop est compilé
sans `netem`, `tbf` ni cible `NFQUEUE` : impossible de retarder un paquet
côté noyau. Chaque équipement coupe donc la réponse automatique au ping
(`sysctl net.ipv4.icmp_echo_ignore_all=1`, propre à son espace réseau) et
`icmp_responder.py` répond lui-même, après le délai du lien et avec ses
pertes. Les pertes et coupures SNMP passent par iptables (module
`statistic`, présent dans ce noyau). Le ping de Zabbix mesure lui-même le
temps d'aller-retour.

Le VSAT est réglé à ~380 ms et non aux ~600 ms d'un vrai satellite
géostationnaire : le ping de Zabbix abandonne une réponse au-delà de
500 ms et déclarerait le site en panne plutôt que lent.

Les noms sont préfixés `LAB-` et les sites « Laboratoire … » : ils ne se
confondent jamais avec l'inventaire de l'agence.

## Poste de 8 Go : ce qui a été allégé

Docker Desktop n'alloue ici que ~3,8 Go à sa machine virtuelle. Zabbix tourne
en images Alpine (les plus légères publiées) avec des caches et des
processus réduits à un laboratoire d'une vingtaine d'hôtes, et une base
PostgreSQL bridée (`shared_buffers` 48 Mo, 60 connexions) — voir
`docker-compose.yml`. Mesuré : ~310 Mo pour Zabbix complet, ~16 Mo par
équipement du réseau de laboratoire.

## Brancher le NOC sur le laboratoire

Le collecteur lit l'outil désigné par `ZABBIX_API_URL` dans `.env`. Pour le
laboratoire : `ZABBIX_API_URL=http://zabbix-web:8080` et les identifiants
`ZABBIX_LAB_*` (le `.env` du poste contient les deux blocs, celui de
l'agence commenté). Puis `docker compose up -d collector backend`.

## Peupler avec l'inventaire réel

```bash
docker compose --profile provision run --rm provision
docker compose exec centreon /usr/local/bin/provision-lab
```

Ces deux commandes déclarent, dans Zabbix/Centreon/iTop, **les machines qui
tournent réellement sur cette pile** — le backend du NOC, son frontend,
Redis, PostgreSQL, et les outils eux-mêmes — et les font superviser par de
**vraies sondes** : agent Zabbix, `check_ping` ICMP côté Centreon, CI dans
la CMDB iTop.

Nagios n'a besoin d'aucune commande : son inventaire est un fichier de
configuration, `nagios/noc-lab.cfg`, monté en lecture seule dans le
conteneur — les mêmes conteneurs réels, sondés par `check_ping`,
`check_http` et `check_tcp`. Le modifier puis `docker compose restart nagios`.

Aucune donnée n'est inventée. C'est ce qui distingue ce laboratoire d'un jeu
d'essai : un jeu de données semé en base ne traverse aucune ligne de code
d'API et ne prouve rien sur la capacité du NOC à lire Zabbix. Ici, chaque
valeur affichée a franchi le connecteur, l'API réelle de l'outil, sa base et
sa sonde. Arrêtez le conteneur `frontend`, et une vraie alerte apparaît dans
le NOC en moins de cinq minutes.

Le provisionnement est **idempotent** : le relancer ne crée pas de doublons.

## Ce que fait chaque image

### `centreon/` — Centreon 22.10.7

> ⚠️ **Image non constructible depuis octobre 2026.** Centreon a retiré de
> `packages.centreon.com` les dépôts 22.10, 23.04, 23.10 et 24.04 (« does not
> have a Release file ») ; seule la branche 24.10 (Debian 12) reste publique,
> et aucune image Docker complète (interface + API) de la 22.10 n'existe — les
> images communautaires ne sont que des collecteurs. Deux voies : obtenir de
> l'agence les paquets `.deb`/`.rpm` de son serveur 22.10 (cache apt/yum ou
> miroir interne) pour reconstruire à l'identique, ou bâtir sur 24.10, dont
> l'API v2 lue par le NOC est la même. En attendant, `CENTREON_API_URL` est
> commentée dans `.env` : le connecteur se déclare « non configuré ».

Centreon ne publie aucune image Docker supportée. L'image installe les
paquets Debian de l'éditeur depuis `packages.centreon.com`, exactement comme
le ferait une installation manuelle suivant la documentation officielle.

Trois points méritent d'être connus avant d'y toucher :

* **L'installation est déroulée sans interaction par l'assistant web
  lui-même.** Centreon n'a pas d'installateur en ligne de commande ; la
  seule installation supportée est l'assistant, dont chaque étape est un
  point d'entrée HTTP sous `install/steps/`. `docker-entrypoint.sh` les
  appelle avec `curl` dans l'ordre exact où le navigateur les enchaîne. Ce
  n'est pas un contournement, c'est l'installation officielle automatisée.

* **L'épinglage de version ne porte que sur l'interface web**, et c'est
  volontaire. La branche 22.10 versionne chaque composant indépendamment :
  le dépôt propose `centreon-web` en 22.10.31, `centreon-broker` en 22.10.12
  et `centreon-gorgone` en 22.10.9. Le « 22.10.7 » de l'agence est la
  version de `centreon-web` — celle qu'affiche *Administration → À propos*.
  Tout épingler à 22.10.7 rend l'ensemble insoluble : `centreon-engine`
  exige `centreon-common ≥ 22.10.12`.

* **Une dépendance Perl manquante est comblée.** `centreon-gorgone` 22.10
  ne déclare pas `Clone::Choose`, dépendance transitive de `Hash::Merge`.
  Sans elle, le démon meurt au démarrage sur `Can't locate Clone/Choose.pm`
  et l'export de configuration échoue en silence. C'est un défaut
  d'empaquetage de l'éditeur.

### `itop/` — iTop 3.2.3-2

Aucune image officielle Combodo n'existe et les images communautaires
s'arrêtent à 3.2.2. Celle-ci part de l'image PHP officielle et déploie
l'archive publiée par Combodo sur GitHub.

* **L'installation utilise l'installateur sans interaction de Combodo**
  (`web/setup/unattended-install/unattended-install.php`), avec un fichier
  de réponses XML généré depuis l'environnement.

* **`sample_data` vaut 0.** iTop propose d'installer un jeu de données de
  démonstration — organisations, contacts et tickets fictifs. On le refuse :
  la CMDB ne doit contenir que des objets réels.

* **Le compte de service porte QUATRE profils, pas un.** C'est le piège
  classique d'iTop : « REST Services User » n'accorde aucun droit sur les
  données, il ouvre seulement la porte de `/webservices/rest.php`. Un compte
  qui ne porte que lui reçoit un HTTP 200 contenant
  `{"code":1,"message":"not enough permissions"}` — un refus d'habilitation
  qui ressemble à une panne d'API. iTop 3.2 ne livrant aucun profil en
  lecture seule, on retient la combinaison la plus étroite qui couvre ce que
  le NOC lit.

### `nagios/` — Nagios Core 4.5.12

Image `jasonrivers/nagios`, version épinglée. Le collecteur lit les CGI JSON
livrés avec Nagios Core (`NAGIOS_MODE=statusjson`), sans module
supplémentaire.

* **Les CGI JSON codent les états en masques de bits** (hôte : 2 UP,
  4 DOWN, 8 UNREACHABLE ; service : 2 OK, 4 WARNING, 8 UNKNOWN,
  16 CRITICAL), et non avec les codes de retour des sondes. Voir l'en-tête
  de `integrations/nagios.py`.
* **Le compte `nagiosadmin`** est créé au démarrage avec `NAGIOS_API_USER` /
  `NAGIOS_API_PASSWORD` ; c'est le seul que le `cgi.cfg` de l'image autorise
  à voir tous les hôtes.
* Le frontend du NOC n'est pas déclaré : il n'est pas sur le réseau
  `default`, la sonde le verrait toujours DOWN.

### `provision/` — peuplement du laboratoire

Script Python sans dépendance hors bibliothèque standard. Deux corrections
qu'il applique méritent d'être signalées, parce qu'elles produisent sinon de
fausses alertes permanentes :

* **L'hôte « Zabbix server » d'une installation neuve** a son interface
  agent sur `127.0.0.1`, l'adresse du conteneur du *serveur*, où aucun agent
  ne tourne. Le script la repointe sur le conteneur `zabbix-agent`.
* **Les interfaces sont créées en mode DNS**, jamais par adresse IP : les
  adresses de conteneurs changent à chaque recréation, les noms de service
  Docker non.

## Pièges rencontrés, et comment les reconnaître

Ces problèmes ont tous été rencontrés en montant cette pile. Ils reviendront.

| Symptôme | Cause réelle |
|---|---|
| `PostgreSQL server is not available` en boucle, alors que la base est saine | Le mot de passe passé ne correspond plus à celui qui a créé le volume. Le plus souvent : une variable **dupliquée** dans `.env` — Compose retient la dernière occurrence, en silence. |
| `Unsupported redo log format` au démarrage de MariaDB | Le volume a été créé par une version plus récente. Un volume de base ne se rétrograde pas : le supprimer et laisser l'outil se réinstaller. |
| `exec /usr/local/bin/docker-entrypoint.sh: no such file or directory` | Fins de ligne CRLF. Le noyau cherche l'interpréteur `/bin/bash\r`. Le `.gitattributes` de la racine force les `.sh` en LF. |
| Le conteneur Centreon sort en code **0** au redémarrage | Fichier PID Apache périmé : `apache2ctl` croit qu'un serveur tourne, sort proprement, et le conteneur s'arrête sans erreur. Corrigé dans l'entrypoint. |
| `docker compose rm -f` ne supprime rien | Un conteneur en marche n'est pas supprimé sans `-s`. La purge de volume qui suit échoue alors en silence. |
| Zabbix : `Incorrect arguments passed to function` sur `host.create` | Une interface en mode DNS exige quand même la clé `ip`, fût-elle vide. Le message ne nomme ni le champ ni l'objet. |

## Remettre à zéro un outil

Supprimer les volumes force une réinstallation propre. **Arrêter les
conteneurs d'abord** (`-s`), sinon la suppression échoue sans le dire :

```bash
docker compose --profile tools rm -f -s itop itop-db
docker volume rm noc_itop_dbdata noc_itop_html
docker compose --profile itop up -d
```

## Ce qui n'est pas dans le laboratoire

**Nokia NSP — un simulateur, pas un vrai NSP.** Nokia ne distribue pas NSP :
aucune instance ne peut être montée. Un **simulateur** (`tools/nsp-sim`,
profil `nsp`) répond aux requêtes du connecteur (`integrations/nsp.py`) dans
les deux modes, pour voir des données NSP dans le NOC :

```bash
docker compose --profile nsp up -d --build nsp-sim
# .env :
#   NSP_API_URL=http://nsp-sim:8080
#   NSP_API_USER=admin
#   NSP_API_PASSWORD=NspLab!2026
#   NSP_FM_MODE=yang            # ou classic : alarmes seules, sans inventaire
docker compose up -d collector backend
```

* **Scénario** : `tools/nsp-sim/scenario.json`, relu à chaud quand il change.
  Il contient 8 équipements du réseau de transport (1830 PSS, 7750 SR,
  7705 SAR, Wavence), tous préfixés `LAB-`, et 5 alarmes, dont une
  « cleared » que le NOC doit ignorer. `LAB-GAOUA-WAVENCE-01` tombe seul
  15 minutes au début de chaque heure, avec son alarme (`flap`).
* **Pilotage** (port local 8086, sans authentification) :

  ```bash
  curl http://localhost:8086/_sim/state                       # état courant
  curl -X POST http://localhost:8086/_sim/alarms -H 'Content-Type: application/json' \
       -d '{"ne_id":"LAB-NSP-7","severity":"critical","text":"Coupure fibre"}'
  curl -X DELETE http://localhost:8086/_sim/alarms/<id>      # effacer
  curl -X POST http://localhost:8086/_sim/ne/LAB-NSP-3/state -H 'Content-Type: application/json' \
       -d '{"state":"down"}'
  ```

  Une alarme levée à la main disparaît au redémarrage du conteneur.
* **Limite** : le simulateur a été écrit d'après ce que le connecteur
  attend. Il montre comment le NOC affiche, fusionne et alerte sur des
  données NSP ; il **ne prouve pas** que le connecteur fonctionne avec le NSP
  de l'agence. Cette preuve vient du diagnostic sur l'instance réelle
  (`python -m collector.probe nsp`, documentation chapitre 9).
* Les équipements simulés n'ont ni site ni région : le connecteur NSP ne lit
  aucune localité, ils sont comptés sous « Région non renseignée ».

**Un serveur NetXMS.** Le connecteur API (`integrations/netxms.py`) reste
dans le code, mais le laboratoire ne monte plus de serveur NetXMS : seule la
base du dump de production est servie (`netxms-db`, profil `netxms`) :
restauré depuis `database/netxmsbd07082026.sql` et lu en lecture seule par
`integrations/netxms_db.py` — voir le README principal. Aucun serveur
`netxmsd` n'est démarré sur cette base précise : il exécuterait les actions
de production (courriels, Telegram) vers de vraies personnes. Ce dump ne
doit jamais quitter le poste où il a été restauré, préproduction comprise.

Deux réglages restent à confirmer auprès de l'agence :

* `NAGIOS_MODE` — `statusjson` (Nagios Core 4.x, le cas le plus fréquent),
  `livestatus`, ou `xi` ;
* `NSP_FM_MODE` — `yang` (recommandé par Nokia) ou `classic`.

Tant qu'ils valent `unknown`, les connecteurs se déclarent non configurés en
**nommant la variable à renseigner**, plutôt que de se faire passer pour un
outil en panne.

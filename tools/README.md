# Instances locales des outils sources

Ce répertoire monte, sur le poste de développement, les **mêmes versions**
d'outils que celles exploitées en production par l'agence :

| Outil | Version | Interface | API interrogée par le collecteur |
|---|---|---|---|
| Zabbix | **7.0.23** | <http://localhost:8081> — `Admin` / `zabbix` | `http://zabbix-web:8080/api_jsonrpc.php` |
| Centreon | **22.10.7** | <http://localhost:8084/centreon> — `admin` | `http://centreon/centreon/api/latest` |
| iTop | **3.2.3-2** (build 20678) | <http://localhost:8082> — `admin` | `http://itop/webservices/rest.php` |

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
docker compose --profile zabbix   up -d     # ~1,0 Go
docker compose --profile itop     up -d     # ~0,8 Go
docker compose --profile centreon up -d     # ~2,0 Go
docker compose --profile tools    up -d     # les trois
```

Sur une machine de 8 Go, le mode d'emploi réaliste est : Zabbix et iTop
ensemble, Centreon séparément.

**Premier démarrage.** Centreon et iTop s'installent tout seuls et cela
prend quelques minutes ; les conteneurs ne sont déclarés sains qu'une fois
leur API capable de répondre à une authentification — pas avant. Suivre :

```bash
docker compose logs -f centreon itop
```

## Peupler avec l'inventaire réel

```bash
docker compose --profile provision run --rm provision
docker compose exec centreon /usr/local/bin/provision-lab
```

Ces deux commandes déclarent, dans les trois outils, **les machines qui
tournent réellement sur cette pile** — le backend du NOC, son frontend,
Redis, PostgreSQL, et les outils eux-mêmes — et les font superviser par de
**vraies sondes** : agent Zabbix, `check_ping` ICMP côté Centreon, CI dans
la CMDB iTop.

Aucune donnée n'est inventée. C'est ce qui distingue ce laboratoire d'un jeu
d'essai : un jeu de données semé en base ne traverse aucune ligne de code
d'API et ne prouve rien sur la capacité du NOC à lire Zabbix. Ici, chaque
valeur affichée a franchi le connecteur, l'API réelle de l'outil, sa base et
sa sonde. Arrêtez le conteneur `frontend`, et une vraie alerte apparaît dans
le NOC en moins de cinq minutes.

Le provisionnement est **idempotent** : le relancer ne crée pas de doublons.

## Ce que fait chaque image

### `centreon/` — Centreon 22.10.7

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

**Serveur NetXMS, Nagios et Nokia NSP.** Leurs connecteurs sont écrits et
prêts (`integrations/netxms.py`, `nagios.py`, `nsp.py`) : renseigner
`<OUTIL>_API_URL` dans `.env` suffit à les activer, sans une ligne de code à
écrire. Nokia ne distribue pas NSP publiquement.

NetXMS est présent sous une autre forme : sa **base de production**,
restaurée depuis `database/netxmsbd07082026.sql` dans le service
`netxms-db` (profil `netxms`) et lue en lecture seule par
`integrations/netxms_db.py` — voir le README principal. Aucun serveur
`netxmsd` n'est démarré dessus : il exécuterait les actions de production
(courriels, Telegram) vers de vraies personnes.

Deux réglages restent à confirmer auprès de l'agence :

* `NAGIOS_MODE` — `statusjson` (Nagios Core 4.x, le cas le plus fréquent),
  `livestatus`, ou `xi` ;
* `NSP_FM_MODE` — `yang` (recommandé par Nokia) ou `classic`.

Tant qu'ils valent `unknown`, les connecteurs se déclarent non configurés en
**nommant la variable à renseigner**, plutôt que de se faire passer pour un
outil en panne.

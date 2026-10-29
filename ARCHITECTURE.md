# Architecture de la plateforme NOC

> Ce document décrit la cible et le pourquoi de chaque choix. Pour installer
> et exploiter, voir [README.md](README.md) ; pour les instances locales des
> outils sources, [tools/README.md](tools/README.md).

## 1. Le problème que résout cette architecture

Un NOC agrège des outils qui **stockent déjà tout**. Zabbix conserve ses
mesures brutes et ses tendances horaires jusqu'à un an, Centreon ses RRD,
iTop l'intégralité de ses tickets. La tentation naturelle — et l'architecture
de la version précédente de ce projet — est de recopier ces données dans un
entrepôt maison, PostgreSQL + TimescaleDB, puis de servir les tableaux de bord
depuis cet entrepôt.

Cette approche a trois défauts, dans l'ordre de gravité :

1. **Le coût croît avec le parc, pas avec l'usage.** Une hypertable
   `metric_value` ingérant sept métriques pour quelques centaines
   d'équipements toutes les cinq minutes écrit des millions de lignes par
   jour, pour des données dont l'original existe déjà ailleurs. On paie deux
   fois le même stockage.
2. **La divergence est inévitable.** Un incident acquitté dans Zabbix reste
   « ouvert » dans la copie jusqu'au cycle suivant. L'exploitant voit deux
   vérités contradictoires et cesse de faire confiance au tableau de bord.
3. **La copie ne se rattrape jamais.** Si la collecte s'arrête un week-end,
   il manque un trou dans l'entrepôt que rien ne comblera, alors que la donnée
   est intacte dans l'outil source.

## 2. Les trois familles de données

La réponse n'est pas « tout en mémoire » ni « tout en base » : c'est de
**classer la donnée selon qui en est propriétaire**, et de traiter chaque
famille différemment.

| | Famille 1 — État instantané | Famille 2 — Historique | Famille 3 — Données propres au NOC |
|---|---|---|---|
| **Exemples** | équipements et leur état, alertes actives, disponibilité des outils | courbes de métriques, incidents clos, tickets résolus | comptes et rôles, objectifs SLA, journal d'audit, trace des notifications, bilans journaliers de la collecte |
| **Propriétaire** | l'outil source | l'outil source | **le NOC** |
| **Où ça vit chez nous** | **Redis**, instantané réécrit toutes les 300 s et dernière collecte complète par flux | **nulle part** — requête à la demande vers la source, cache Redis à TTL long | **PostgreSQL**, petite base |
| **Perte acceptable ?** | oui : reconstruit au cycle suivant | oui : la source fait foi | **non** : irrécupérable |
| **Volume** | ~10 à 50 Mo de RAM | 0 | quelques Mo |

Le NOC ne conserve pas de série historique source. Redis garde seulement la
dernière collecte complète par flux pour éviter qu'une panne temporaire d'un
outil efface les équipements ou alertes encore pertinents ; ces données sont
marquées périmées jusqu'à la reprise de la collecte. Un cache incomplet,
mal formé ou sans date de collecte exploitable est rejeté en entier : une
liste partielle ne doit pas être présentée comme le dernier succès complet.

## 3. Schéma d'ensemble

```
   Zabbix 7.0    Centreon 22.10    NetXMS 5.0    Nagios    Nokia NSP    iTop 3.2
   (en production : uniquement leurs API ; chaque outil s'active par son URL)
        │                   │                   │
        │  ①  polling cadencé, 1 série de requêtes / 300 s / outil
        └───────────────────┼───────────────────┘
                            ▼
                  ┌──────────────────┐
                  │   Collecteur     │  normalise en mémoire,
                  │   (asyncio)      │  n'écrit jamais sur disque
                  └────────┬─────────┘
                           │ écrit l'instantané complet
                           ▼
                  ┌──────────────────┐        ┌────────────────────┐
                  │      REDIS       │        │ PostgreSQL (petit) │
                  │ état courant     │        │ comptes, SLA,      │
                  │ + cache historique│       │ audit, notif.,     │
                  └────────┬─────────┘        │ agrégats journaliers│
                           │                  └─────────┬──────────┘
                           │  ② lecture instantanée     │
                           └──────────┬─────────────────┘
                                      ▼
                              ┌───────────────┐
                              │   Backend     │  ③ à la demande, pour une
                              │   FastAPI     │─────▶ courbe ou un rapport :
                              └───────┬───────┘      requête l'outil SOURCE
                                      │              et met en cache
                              REST + WebSocket
                                      ▼
                              ┌───────────────┐
                              │   Frontend    │
                              └───────────────┘
```

### ① Le collecteur — un seul appel par outil, quel que soit le nombre d'écrans

Un worker unique interroge chaque outil toutes les `COLLECT_INTERVAL_S`
secondes (300 par défaut), normalise la réponse en mémoire, et écrit
l'instantané dans Redis. Il n'écrit **rien** sur disque.

Conséquence directe, et c'est le point le plus important pour l'agence :
**les outils sources reçoivent une requête toutes les 300 secondes, que le
tableau de bord compte un opérateur ou quarante.** La charge que le NOC
impose à la production est constante et connue d'avance — c'est l'argument à
présenter à l'équipe sécurité qui a refusé les accès.

### ② La lecture — le chemin chaud ne touche aucune base

Toutes les vues « maintenant » (mur d'alertes, salle de supervision, carte,
inventaire, bandeau d'alertes) lisent **uniquement Redis**. Une lecture
Redis se compte en dizaines de microsecondes : le tableau de bord reste
instantané avec dix opérateurs connectés comme avec un seul.

### ③ L'historique — fédéré, jamais recopié

Quand un exploitant ouvre la courbe de latence d'un équipement sur 24 heures,
le backend interroge Zabbix (`history.get` en deçà d'un jour, `trend.get`
au-delà — la granularité change, pas la source) et met le résultat en cache
Redis. Les neuf opérateurs suivants qui ouvrent la même courbe sont servis
par le cache : **une seule requête part vers l'outil.**

C'est le motif dit de *query federation*, celui de Grafana ou de Perses.

### Ce que PostgreSQL garde, et pourquoi

Trois choses, et rien d'autre :

* **les données propres au NOC** — comptes et rôles, objectifs SLA, journal
  d'audit, abonnements et trace des notifications. Aucun outil source ne les
  connaît : les perdre serait irrattrapable. Le travail d'exploitation
  lui-même (acquitter, affecter, résoudre) n'en fait **pas** partie : il se
  fait dans l'outil source ou dans iTop, et le NOC le relit — sinon il
  tiendrait un second circuit de travail qui divergerait de l'ITSM ;
* **les agrégats journaliers** (`kpi_daily`) — une ligne par jour et par
  site : équipements, pannes, alertes, disponibilité moyenne. Quelques centaines de lignes par jour, soit quelques mégaoctets
  par an. Ils permettent aux courbes du tableau Direction de porter sur six
  ou douze mois sans interroger les outils sur toute la période à chaque
  affichage ;
* **le journal des changements d'état** (`hist_state`, `hist_alert`) — une
  ligne quand un équipement ou un lien change d'état, une ligne par alerte de
  son ouverture à sa fermeture. C'est la seule entorse à « ne rien
  recopier », et elle est délibérée : sans elle, impossible de dire quelle a
  été la disponibilité d'un lien sur l'année, ni de recalculer un bilan
  perdu. Elle reste petite parce qu'elle ne garde que les changements,
  jamais les mesures ;
* rien de plus. **Pas de `metric_value`, pas de `fact_incident`, pas de
  TimescaleDB.**

> **Pourquoi ne pas tout mettre dans Redis, y compris les comptes ?**
> Redis sait persister (AOF), mais son modèle de données ne sait ni contrainte
> d'intégrité, ni transaction multi-clés, ni requête analytique. Une entrée
> d'audit rattachée à un compte, ou une notification qu'un seul backend doit
> envoyer (clé unique servant de verrou), est exactement ce qu'une base
> relationnelle fait bien. Et ce n'est pas là qu'est
> le coût : la table des comptes d'un NOC pèse quelques kilooctets. Ce qui
> coûtait, c'était la copie des métriques — elle a disparu.

## 4. Contrat de l'instantané Redis

Le collecteur écrit, le backend lit. Les deux côtés partagent ce contrat, et
lui seul.

| Clé | Type | Contenu | Durée de vie |
|---|---|---|---|
| `noc:live:nodes` | string (JSON) | tous les équipements normalisés, fusionnés entre outils | `3 × COLLECT_INTERVAL_S` |
| `noc:live:alerts` | string (JSON) | alertes actives, tous outils confondus | `3 × COLLECT_INTERVAL_S` |
| `noc:live:meta` | string (JSON) | horodatage du cycle, durée, compteurs, rapport de fusion, alertes orphelines | `3 × COLLECT_INTERVAL_S` |
| `noc:live:latest` | string (JSON) | dernières mesures par équipement | `3 × COLLECT_INTERVAL_S` |
| `noc:live:maintenance`, `noc:live:work_orders` | string (JSON) | maintenances planifiées, ordres de travail iTop | `3 × COLLECT_INTERVAL_S` |
| `noc:live:trend` | liste (JSON) | historique court, un point par cycle | 24 h glissantes |
| `noc:tool:<outil>` | string (JSON) | joignabilité, latence, dernier succès, dernière erreur | `3 × COLLECT_INTERVAL_S` |
| `noc:source:<outil>:<flux>` | string (JSON) | dernière collecte complète de chaque flux (équipements, alertes, maintenances, interventions) pour reprise et affichage périmé | sans expiration |
| `noc:hist:<empreinte>` | string (JSON) | courbe, historique iTop ou contrat SLT mis en cache | selon la donnée |

**La durée de vie de trois cycles est un choix de sûreté**, pas un réglage
arbitraire : si le collecteur meurt, les clés expirent au bout de quinze
minutes et le backend cesse de servir un état périmé — il répond
explicitement « collecte interrompue » plutôt que d'afficher un parc
faussement calme. Un instantané muet est un incident, pas une absence
d'incident. Les instantanés source distincts servent uniquement de reprise
après une défaillance d'outil : les objets réutilisés portent `stale=true`,
les équipements dont aucun état frais n'est disponible passent à `silent`,
et l'écran d'interopérabilité montre la date de la dernière collecte valide.

## 5. Ce que l'architecture coûte, et ce qu'elle exige

Aucune architecture n'est gratuite. Celle-ci a deux contreparties assumées :

* **L'ouverture d'une courbe dépend de la disponibilité de l'outil source.**
  Si Zabbix est à genoux, la page de détail d'un équipement ne peut pas
  afficher son historique. Le backend applique donc un délai de garde court
  et un disjoncteur, et l'écran indique franchement que la source est
  injoignable — au lieu de faire patienter l'opérateur.
* **Le NOC n'est pas une archive.** Si l'agence veut conserver un historique
  au-delà de la rétention des outils, c'est la rétention des outils qu'il faut
  allonger, pas une copie qu'il faut créer ici. C'est le bon endroit : Zabbix
  sait le faire nativement et bien mieux qu'un entrepôt tiers.

## 6. Ce qui a été retiré par rapport à la version précédente

| Retiré | Raison |
|---|---|
| TimescaleDB et l'hypertable `metric_value` | duplication de l'historique Zabbix/Centreon — la cause du coût |
| Tables `dim_*` et `fact_*` | remplacées par l'instantané Redis pour l'état courant et par `kpi_daily` pour les tendances |
| Celery + Celery beat + trois bases Redis | un ordonnanceur asyncio dans un unique conteneur suffit pour des tâches cadencées ; Celery apportait un courtier, un backend de résultats et deux processus pour un besoin qui n'en demandait aucun |
| `backend/scripts/seed_demo.py`, `database/legacy/generate_seed.py` | jeux de données fictifs — toute donnée affichée provient désormais d'une API d'outil (ou, en local seulement, d'un export de production) |
| Acquittement, affectation, notes et incidents manuels dans le NOC (`ops_alert_state`, `ops_alert_timeline`, `ops_manual_incident`) ; maintenances et interventions saisies dans le NOC (`ops_maintenance_window`, `ops_field_intervention`) | un second circuit de travail, parallèle à iTop, qui divergeait de l'ITSM : ces gestes se font dans l'outil source ou dans iTop, et le NOC les relit |
| Veilleur d'incidents interrogeant `fact_incident` | le collecteur détecte les nouvelles alertes lors de la comparaison entre deux instantanés, et publie directement sur le canal temps réel |

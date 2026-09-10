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
| **Exemples** | équipements et leur état, alertes actives, disponibilité des outils | courbes de métriques, incidents clos, tickets résolus | comptes et rôles, acquittements, notes d'exploitation, fenêtres de maintenance, incidents signalés à la main, abonnements aux notifications |
| **Propriétaire** | l'outil source | l'outil source | **le NOC** |
| **Où ça vit chez nous** | **Redis**, réécrit intégralement toutes les 300 s | **nulle part** — requête à la demande vers la source, cache Redis à TTL long | **PostgreSQL**, petite base |
| **Perte acceptable ?** | oui : reconstruit au cycle suivant | oui : la source fait foi | **non** : irrécupérable |
| **Volume** | ~10 à 50 Mo de RAM | 0 | quelques Mo |

Le critère est simple et se tient : **on ne persiste que ce qu'aucun outil
source ne saurait nous redonner.**

## 3. Schéma d'ensemble

```
   Zabbix 7.0        Centreon 22.10        iTop 3.2
   (+ NetXMS, Nagios, Nokia NSP — connecteurs prêts, activés par URL)
        │                   │                   │
        │  ①  polling cadencé, 1 requête / 300 s / outil
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
                  │ état courant     │        │ comptes, ack,      │
                  │ + cache historique│       │ maintenances,      │
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

* **les données propres au NOC** (`ops_*`, comptes) — un technicien qui
  acquitte à 3 h 12 avec un commentaire produit une information qui n'existe
  dans aucun outil source. La perdre serait irrattrapable ;
* **les agrégats journaliers** (`kpi_daily`) — une ligne par jour, par
  localité et par outil : nombre d'incidents, MTTA, MTTR, disponibilité
  moyenne. Quelques centaines de lignes par jour, soit quelques mégaoctets
  par an. Ils permettent aux courbes du tableau Direction de porter sur six
  ou douze mois sans interroger les outils sur toute la période à chaque
  affichage ;
* rien de plus. **Pas de `metric_value`, pas de `fact_incident`, pas de
  TimescaleDB.**

> **Pourquoi ne pas tout mettre dans Redis, y compris les comptes ?**
> Redis sait persister (AOF), mais son modèle de données ne sait ni contrainte
> d'intégrité, ni transaction multi-clés, ni requête analytique. Un
> acquittement rattaché à un incident et à un compte utilisateur est
> exactement ce qu'une base relationnelle fait bien. Et ce n'est pas là qu'est
> le coût : la table des comptes d'un NOC pèse quelques kilooctets. Ce qui
> coûtait, c'était la copie des métriques — elle a disparu.

## 4. Contrat de l'instantané Redis

Le collecteur écrit, le backend lit. Les deux côtés partagent ce contrat, et
lui seul.

| Clé | Type | Contenu | Durée de vie |
|---|---|---|---|
| `noc:live:nodes` | string (JSON) | tous les équipements normalisés, fusionnés entre outils | `3 × COLLECT_INTERVAL_S` |
| `noc:live:alerts` | string (JSON) | alertes actives, tous outils confondus | `3 × COLLECT_INTERVAL_S` |
| `noc:live:meta` | string (JSON) | horodatage du cycle, durée, compteurs | `3 × COLLECT_INTERVAL_S` |
| `noc:tool:<outil>` | string (JSON) | joignabilité, latence, dernier succès, dernière erreur | `3 × COLLECT_INTERVAL_S` |
| `noc:hist:<outil>:<empreinte>` | string (JSON) | réponse d'historique mise en cache | selon la fenêtre demandée |

**La durée de vie de trois cycles est un choix de sûreté**, pas un réglage
arbitraire : si le collecteur meurt, les clés expirent au bout de quinze
minutes et le backend cesse de servir un état périmé — il répond
explicitement « collecte interrompue » plutôt que d'afficher un parc
faussement calme. Un instantané muet est un incident, pas une absence
d'incident.

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
| `backend/scripts/seed_demo.py`, `database/legacy/generate_seed.py` | jeux de données fictifs — toute donnée affichée provient désormais d'une API ou d'une base d'outil |
| Veilleur d'incidents interrogeant `fact_incident` | le collecteur détecte les nouvelles alertes lors de la comparaison entre deux instantanés, et publie directement sur le canal temps réel |

# 11. Les données affichées : origine, fraîcheur, calcul

Ce chapitre répond, pour chaque chiffre du NOC, à trois questions :
**d'où vient-il**, **quand change-t-il**, **comment est-il calculé**. C'est la
référence à consulter quand un utilisateur demande « pourquoi ce chiffre ? »
ou « pourquoi n'a-t-il pas bougé ? ».

## Les trois rythmes

Toute donnée affichée suit l'un de ces trois rythmes.

| Rythme | Source | Quand la donnée change | Où elle vit |
|---|---|---|---|
| **① À chaque collecte** | Instantané écrit par le collecteur | Toutes les `COLLECT_INTERVAL_S` secondes (300 par défaut) | Redis, expire après 3 cycles |
| **② Une fois par jour** | Bilans journaliers `kpi_daily` | Chaque nuit à `ROLLUP_HOUR` (1 h par défaut), pour **la veille** | PostgreSQL |
| **③ À la demande** | L'outil source (iTop, ou Zabbix/Centreon/NetXMS pour les courbes) | À l'ouverture de l'écran, puis gardée en cache (5 min pour iTop) | Cache Redis |
| **④ Journal historique** | Périodes d'état et alertes, écrites par le collecteur | À chaque cycle, mais seulement quand un état change | PostgreSQL (`hist_state`, `hist_alert`) |

Le navigateur relit l'API à son propre rythme (`REFRESH` dans
`frontend/src/hooks/queries.js`) : 20 s pour les vues en direct, 60 s pour
l'inventaire et les opérations, 5 min pour les tendances, jamais
automatiquement pour les courbes. Une nouvelle alerte reçue par WebSocket
déclenche un rafraîchissement immédiat. **Relire plus souvent ne rend pas la
donnée plus fraîche** : une donnée ① ne change qu'au cycle suivant, une
donnée ② qu'au lendemain.

### ① À chaque collecte

À chaque cycle, le collecteur lit tous les outils, fusionne et écrit dans
Redis (chapitre 2, flux 1) :

- l'état de chaque équipement et ses faits de fiche (inventaire, interfaces,
  disponibilité calculée par l'agence, panne en cours, dernier démarrage) ;
- les alertes actives des outils et les tickets iTop **ouverts** ;
- les maintenances en cours et à venir, les ordres de travail iTop ;
- les dernières mesures du parc (latence, pertes, débits, CPU…) ;
- la santé de chaque outil et le rapport de fusion ;
- un point d'**historique court** (24 h glissantes) : disponibilité,
  équipements hors service, alertes, incidents.

Si un outil ne répond pas, sa dernière collecte réussie est reprise et
marquée « périmée » ; si le collecteur s'arrête, l'instantané expire au bout
de 3 cycles (15 min) et les écrans affichent « collecte interrompue ».

### ② Une fois par jour

À chaque cycle, le collecteur ajoute ses observations à des compteurs **en
mémoire**, par jour et par localité (le parc entier, chaque région, chaque
province, chaque site) : équipements, en service, hors service, dégradés, en
maintenance, alertes, alertes critiques. Chaque nuit à `ROLLUP_HOUR`, il
écrit **une ligne par localité pour la veille** dans `kpi_daily`, avec des
moyennes sur le nombre de cycles réellement exécutés (`samples`).

Conséquences à connaître :

- **La journée en cours n'apparaît jamais** dans ces vues : il faut attendre
  le lendemain matin.
- **Pas de rattrapage du passé** : un NOC qui vient d'être installé n'a pas
  d'historique ; les vues sur 6 et 12 mois se remplissent jour après jour.
- **Un redémarrage du collecteur** en cours de journée reprend les compteurs
  du jour, sauvegardés dans Redis à chaque cycle.
- **Une écriture de nuit en échec** (base indisponible) est réessayée toutes
  les 15 minutes jusqu'à réussir ; un collecteur arrêté à l'heure du bilan
  l'écrit à son redémarrage. Un jour resté malgré tout sans bilan est
  recalculé depuis le journal historique, pondéré par le temps.
- Les heures où le collecteur était arrêté manquent à la moyenne du jour :
  elle porte sur les cycles réellement exécutés.
- `ROLLUP_ENABLED=false` coupe complètement ces bilans.

### ③ À la demande

Les tickets iTop **clos** ne sont jamais copiés : pour les SLA, les
indicateurs d'incidents et le rapport, le backend demande à iTop les tickets
ouverts sur la période, et garde la réponse **5 minutes**. Les engagements
contractuels iTop (SLT) suivent la même règle. Les **courbes** d'un
équipement ou du réseau sont lues dans Zabbix, Centreon ou NetXMS à
l'ouverture, puis mises en cache. Si l'outil ne répond pas, l'écran le dit
au lieu d'afficher zéro.

## Écran par écran

Légende : ① collecte · ② journalier · ③ à la demande.

### Pilotage — Directeur (`/direction`)

| Panneau | Rythme | Contenu |
|---|---|---|
| Tuile « Disponibilité du réseau » | ① | Disponibilité instantanée du périmètre |
| Moyenne du mois, écart avec le mois précédent | ② | Moyenne des disponibilités journalières |
| Tuiles « Équipements en panne », « Incidents iTop ouverts » | ① | |
| Tuile « Respect des SLA (30 j) », « Engagements par gravité (30 j) » | ③ | Tickets iTop des 30 derniers jours |
| Classement par région / province / site (« clic pour descendre ») | ① | État à l'instant |
| Points d'attention | ① et ③ | Disponibilité et incidents à l'instant, engagements SLA sur 30 j |
| **Évolution sur 6 mois** | ② | Disponibilité moyenne quotidienne |
| KPI incidents (grille de l'agence), Principales causes, Équipements récurrents, Top 10 des sites les plus incidentés | ③ (et ① pour la file en cours) | Tickets iTop des 30 derniers jours |
| Disponibilité par organisation | ① et ③ | Disponibilité des CI de l'organisation à l'instant ; incidents et SLA sur 30 j |

### Salle de supervision — Chef NOC (`/supervision`)

| Panneau | Rythme |
|---|---|
| Tuiles, Parc supervisé, Alertes ouvertes, Heure d'apparition des alertes | ① |
| Tendance réseau (24 h) | ① — un point par cycle |
| Collecte ETL, Maintenances en cours, Équipements hors service, Équipements les plus alertants | ① |
| **Sites les plus touchés sur 30 j** | ② — moyennes journalières |
| Alertes en cours | ① |

### Console d'exploitation — Technicien (`/console`)

Tout est ① : tuiles (critiques, majeurs, à traiter, sites touchés,
équipements hors service), file de traitement, répartition des alertes,
réseau sur 24 h (historique court), équipements hors service.

### Incidents iTop (`/incidents`)

| Panneau | Rythme |
|---|---|
| Tickets ouverts, ancienneté, circuit de traitement, par région, par organisation, SLA en cours | ① |
| Historique des tickets (période choisie) | ③ |
| Fiche d'incident : ticket, équipement chez chaque outil, alertes liées, événement Zabbix d'origine | ① |

### Alertes outils (`/alertes`)

Tout est ① : alertes actives de Zabbix, Centreon, NetXMS, Nagios et NSP,
répartition par outil, ancienneté. La fiche d'une alerte montre le contexte
de l'outil (tags, donnée opérationnelle, cause, commentaires
d'acquittement) tel qu'il était au dernier cycle.

### Territoire (`/territoire`)

| Panneau | Rythme |
|---|---|
| Carte, fil d'Ariane, disponibilité, équipements en panne, alertes, incidents par localité, fiche d'un site | ① |
| Respect des SLA par localité (30 j) | ③ |

### Équipements et fiche d'équipement (`/equipements`)

| Donnée | Rythme |
|---|---|
| Inventaire, état, état chez chaque outil, outil muet, conflits | ① |
| Dernières mesures (tuiles) | ① |
| Fiche technique : inventaire, interfaces, disponibilité calculée par l'agence, hors service depuis, dernier démarrage | ① |
| **Télémétrie (courbes)** | ③ — lue dans l'outil source |
| Historique de disponibilité (7 j à 1 an) : disponibilité, temps hors service, pannes, durée moyenne d'une panne, MTBF, MTTR des alertes, frise des états, liens surveillés | ④ |
| Organisation, dernière mesure | ① |

### Performance réseau (`/performance`)

| Donnée | Rythme |
|---|---|
| Tuiles (disponibilité, latence, pertes, débits, CPU…) | ① — dernières valeurs |
| Liens et interfaces, disponibilité calculée par l'agence | ① |
| Courbe agrégée et classement | ③ — échantillon d'au plus 50 équipements |
| Les moins disponibles sur la durée (équipements ou liens, 7 j à 1 an) | ④ |

### SLA & disponibilité (`/sla`)

| Donnée | Rythme |
|---|---|
| Respect des SLA, évolution par semaine, délais de résolution, par localité, par gravité | ③ |
| Incidents à risque | ① |
| Contrat iTop (SLT) | ③ |
| Objectifs du NOC | Base du NOC, modifiés à la main |

### Rapports (`/rapports`)

| Donnée | Rythme |
|---|---|
| Historique sur 12 mois, disponibilité et sites du rapport | ② |
| Incidents, délais, causes et dépassements du rapport | ③ — tickets iTop du mois |

### Autres écrans

| Écran | Rythme |
|---|---|
| Maintenances, Interventions | ① (changements et ordres de travail iTop, maintenances Zabbix) |
| Collecte ETL | ① ; la courbe de couverture vient de l'historique court |
| Mur d'écrans (`/mur`) | ① |
| Utilisateurs, Journal d'audit | Base du NOC, à chaque action |

## Comment chaque indicateur est calculé

### Disponibilité

| Indicateur | Formule | Code |
|---|---|---|
| **Disponibilité instantanée** | équipements « en service » ÷ (équipements − équipements en maintenance) | `live_service.fleet_summary` |
| Santé du parc | équipements « en service » ÷ équipements, maintenance comprise | idem |
| **Disponibilité journalière** | Σ des « en service » observés à chaque cycle ÷ (Σ équipements − Σ en maintenance) | `collector/rollup.py` |
| Disponibilité du mois | moyenne des disponibilités journalières | `kpi_service.monthly_summary` |
| Écart avec le mois précédent | publié seulement si le mois précédent a **au moins 15 jours** de bilans ; sinon « — » | idem |

Un équipement hors service, dégradé, muet ou d'état inconnu n'est **jamais**
compté disponible. Un équipement en maintenance planifiée sort du
dénominateur. La disponibilité réseau est un indicateur, pas un SLA mesuré.

### Disponibilité sur la durée (journal historique)

| Indicateur | Définition |
|---|---|
| **Disponibilité d'un équipement ou d'un lien** | temps « en service » ÷ (temps observé − maintenance) sur la période |
| Non observé | temps sans observation (avant la mise en service du journal, collecteur arrêté, outil muet plus de 3 cycles) : publié à part, ni pour ni contre |
| Pannes | périodes « hors service » commencées dans la période |
| Durée moyenne d'une panne | moyenne des périodes « hors service » closes |
| MTBF | temps « en service » ÷ nombre de pannes |
| MTTR des alertes | durée moyenne des alertes techniques closes dans la période |
| Lien surveillé | interface activée que NetXMS attend active (NetXMS seulement) |

Un changement d'état est daté du cycle où il est vu : précision de
`COLLECT_INTERVAL_S` (5 min). L'ouverture d'une alerte est la date donnée
par l'outil.

### Délais et SLA (tickets iTop)

| Indicateur | Définition |
|---|---|
| **TTO** (prise en charge) | date d'affectation − date d'ouverture du ticket |
| **TTR** (résolution) | date de résolution − date d'ouverture |
| **MTTO / MTTR** | moyennes des TTO / TTR sur les tickets qui ont ces dates ; la médiane et le nombre de tickets sont affichés à côté |
| État d'un ticket | **tenu** (résolu dans l'objectif), **dépassé** (résolu hors objectif, ou encore ouvert et déjà hors objectif), **en cours** (ouvert, dans l'objectif), **sans objectif** |
| **Respect des SLA** | (tickets évalués − dépassés) ÷ tickets évalués ; « évalués » = tenus + dépassés, les tickets en cours n'y entrent pas |
| **Incidents à risque** | tickets ouverts dont l'objectif de résolution est dépassé ou à **moins de 25 %** du délai restant |

Objectifs installés par défaut (`backend/sql/schema.sql`, modifiables par le
Directeur ou le Chef NOC sur l'écran SLA, chaque modification est tracée
dans le journal d'audit) :

| Gravité | Prise en charge | Résolution |
|---|---|---|
| Critique | 15 min | 4 h |
| Majeure | 30 min | 8 h |
| Moyenne | 2 h | 24 h |
| Mineure | 8 h | 3 j |

La gravité d'un ticket vient de sa **priorité iTop** (1 critique, 2 majeure,
3 moyenne, 4 mineure). Les engagements contractuels iTop (SLT) sont affichés
à côté, sans remplacer ces objectifs.

### Indicateurs d'incidents (`/kpi/incidents`, 30 jours)

| Indicateur | Définition |
|---|---|
| Incidents | tickets iTop **ouverts** pendant la période, clos ou non |
| Résolus, taux de résolution | tickets avec date de résolution **et** statut « résolu » ou « clos », ÷ incidents |
| Réouverts | tickets avec une date de résolution mais un statut ni résolu ni clos (iTop ne compte pas les réouvertures) |
| Causes | code de résolution iTop des tickets résolus |
| Sans cause identifiée | tickets résolus sans code de résolution, ÷ résolus ; « — » si le champ n'existe pas dans l'instance |
| **Équipements récurrents** | équipements visés par **au moins 3 tickets** sur la période |
| Top des sites, par organisation | tickets de la période regroupés par site, puis par organisation du CI iTop |

La **grille de l'agence** (tableau Direction) compare ces valeurs à des
cibles fixées dans `frontend/src/components/domain/IncidentInsights.jsx` :
conforme si la cible est tenue, « à surveiller » si l'écart reste dans 10 %
de la cible (au moins une unité), non conforme au-delà.

| Indicateur | Cible |
|---|---|
| Incidents ouverts sur 30 j | ≤ 100 |
| Incidents en cours | ≤ 20 |
| Incidents critiques / majeurs (30 j) | ≤ 5 / ≤ 10 |
| Taux de résolution | ≥ 95 % |
| Incidents en retard | ≤ 5 |
| Incidents récurrents | ≤ 10 |
| MTTA / MTTR | ≤ 15 min / ≤ 4 h |
| Respect des SLA | ≥ 95 % |
| Incidents sans cause, réouverts | ≤ 5 % |
| Incidents non affectés | ≤ 5 |
| Critiques non traités | 0 |

### Réseau et liens

| Indicateur | Définition |
|---|---|
| Moyennes du parc (latence, pertes, CPU…) | dernière valeur de chaque équipement qui mesure la métrique, chaque équipement compté une fois ; le nombre d'équipements mesurés est affiché |
| Courbe réseau | échantillon stable d'au plus 50 équipements, moyenné par minute et par équipement, puis entre équipements |
| **Liens surveillés actifs** | interfaces que NetXMS attend actives et qui le sont ÷ interfaces attendues actives |
| Interfaces activées actives | interfaces activées par l'administrateur qui transmettent ÷ interfaces activées (ports libres compris) |
| Capacité active | somme des débits nominaux des interfaces actives |
| Disponibilité calculée par l'agence | moyenne des attributs NetXMS `perAvailability`, `mttr`, `mtbf`, `NumFailures`, calculés par un script de l'agence, sur les équipements qui les portent |

Le **taux d'utilisation de la bande passante** n'est pas calculé : le débit
nominal des interfaces est connu, mais pas leur trafic dans le même cycle.

## Cas particuliers

- **Données figées** : avec le dump NetXMS ou l'export du journal Centreon,
  chaque cycle produit le même instantané ; les bilans journaliers répètent
  la même disponibilité jour après jour et aucune notification ne part.
- **Outil muet** : ses équipements restent affichés avec leur dernier état
  connu (fiche équipement : « muet — dernier état … »), sans contredire les
  outils qui répondent.
- **Conflit entre outils** : deux outils qui voient un même équipement dans
  deux états différents le rendent « inconnu » ; la fiche montre ce que voit
  chacun.
- **Équipement sans localité** : compté sous « Région non renseignée »,
  visible et classé en dernier.

# 1. Comprendre le projet

## Le contexte

L'**ANPTIC** exploite le **RESINA**, le réseau informatique qui relie les
ministères, directions régionales et structures de l'administration. Des
centaines de sites et plus d'un millier d'équipements (routeurs, switchs,
serveurs, liaisons radio, pylônes) sont surveillés en permanence.

Cette surveillance est répartie entre **plusieurs outils**, installés au fil
du temps et qui ne se parlent pas :

| Outil | Ce qu'il fait à l'agence |
|---|---|
| **Zabbix** | Supervision : sondes, mesures (CPU, latence, trafic), alertes |
| **Centreon** | Supervision : hôtes, services, alertes |
| **NetXMS** | Supervision du réseau : nœuds, interfaces, alarmes |
| **iTop** | CMDB (inventaire et responsables) et gestion des tickets |
| **Nagios**, **Nokia NSP** | Supervision complémentaire, réseau de transport |

Un opérateur qui veut savoir « qu'est-ce qui est en panne en ce moment ? » doit
ouvrir quatre ou cinq consoles, chacune avec son vocabulaire, ses noms
d'équipement et ses niveaux de gravité.

## Ce que fait la plateforme

Le **NOC** (*Network Operations Center*, centre de supervision) est la salle
où l'équipe surveille le réseau. Cette plateforme est **son tableau de bord
unique**. Elle :

1. **lit** tous les outils par leurs API, à intervalle régulier (toutes les
   5 minutes) ;
2. **traduit** leurs données dans un vocabulaire commun (une gravité
   « critique » veut dire la même chose partout) ;
3. **fusionne** les équipements vus par plusieurs outils en un seul parc ;
4. **affiche** l'état du réseau, les alertes et les indicateurs, avec un écran
   adapté à chaque métier ;
5. **éclaire le traitement** sans le doubler : une alerte s'acquitte dans son
   outil, un incident se traite dans iTop, et le NOC montre côte à côte le
   ticket, l'état de l'équipement chez chaque outil et ses alertes ;
6. **prévient** l'équipe d'une alerte grave par courriel, SMS ou notification
   navigateur ;
7. **mesure** le service rendu : disponibilité, délais de prise en charge et
   de résolution des tickets iTop (MTTO, MTTR), respect des engagements (SLA), rapports
   mensuels.

Ce qu'elle **ne fait pas**, délibérément : elle ne remplace pas les outils de
supervision, n'installe pas de sondes, et **ne recopie pas leurs données**.
Elle lit, elle agrège, elle mesure. Le chapitre
[Architecture](02-architecture.md) explique pourquoi.

## Les utilisateurs et leurs écrans

Le besoin a été exprimé par l'agence dans le document *« informations
essentielles par profil »* (à la racine du dépôt), qui définit **quatre
niveaux de lecture**. Chacun correspond à un rôle et à un écran d'accueil.

| Niveau | Rôle | Écran d'accueil | Ce qu'il y cherche |
|---|---|---|---|
| 1 — Décideur | **Directeur** | `/direction` — Pilotage | Disponibilité globale, incidents critiques, SLA, MTTR, top 10 des sites, tendances, rapports. **Aucun geste d'exploitation.** |
| 2 — Chef NOC | **Chef NOC** | `/supervision` — Salle de supervision | État du réseau, alertes en cours, incidents iTop et leur affectation, santé de la collecte, équipements hors service, maintenances. **Gère aussi les comptes.** |
| 3 — Agent NOC | **Technicien** | `/console` — Console d'exploitation | Les alertes des outils et les incidents iTop en cours, les sites touchés. |
| 4 — Terrain | **Agent terrain** | `/interventions` | Les interventions (ordres de travail iTop). |

À côté des écrans d'accueil, des **écrans transverses** sont partagés selon
les droits :

| Écran | Adresse | Contenu |
|---|---|---|
| Territoire | `/territoire` | Carte et descente région → province → site → équipement |
| Incidents iTop | `/incidents` | Les tickets iTop ouverts, leur SLA, l'historique et les indicateurs (récurrents, causes, dépassements) |
| Alertes outils | `/alertes` | Les alertes techniques de Zabbix, Centreon, NetXMS, Nagios, NSP |
| Équipements | `/equipements` | L'inventaire fusionné, et la fiche de chaque équipement (mesures, inventaire, interfaces, état chez chaque outil) |
| Performance réseau | `/performance` | Courbes de latence, pertes, trafic ; disponibilité des liens |
| SLA & disponibilité | `/sla` | Respect des engagements de service, incidents à risque, contrat iTop |
| Rapports | `/rapports` | Rapport mensuel PDF / DOCX |
| Maintenances | `/maintenances` | Maintenances planifiées lues dans iTop (changements) et Zabbix — lecture seule |
| Interventions | `/interventions` | Ordres de travail iTop — lecture seule |
| Collecte ETL | `/integrations` | L'état de la lecture de chaque outil, la qualité de la fusion, les équipements vus par un seul outil, les alertes sans équipement |
| Utilisateurs | `/utilisateurs` | Gestion des comptes (Chef NOC) |
| Journal d'audit | `/audit` | Connexions, comptes, objectifs SLA : qui a fait quoi, quand, depuis où (Chef NOC, Directeur) |
| Mon compte | `/compte` | Ses identifiants et préférences |
| Mur d'écrans | `/mur` | Résumé plein écran des incidents iTop (tout le réseau) pour la salle |

## Le cycle de vie d'une panne

Voici ce qui se passe, de bout en bout, quand un routeur tombe :

1. **Détection** — la sonde de Zabbix (ou NetXMS, Centreon…) constate que le
   routeur ne répond plus et ouvre un *problème* dans l'outil.
2. **Collecte** — au plus 5 minutes plus tard, le collecteur du NOC lit
   l'outil, voit une alerte qui n'existait pas au cycle précédent.
3. **Diffusion** — l'alerte apparaît immédiatement sur tous les écrans ouverts
   (WebSocket), et si elle est critique ou majeure, un courriel part vers les
   personnes abonnées.
4. **Prise en charge** — un ticket est ouvert dans **iTop** et affecté à un
   agent. Le délai entre ouverture et affectation est le **MTTO**.
5. **Intervention** — si un déplacement est nécessaire, un **ordre de
   travail** iTop est créé ; le NOC l'affiche dans Interventions.
6. **Résolution** — le ticket est résolu dans iTop, avec son **code de
   résolution** (la cause). Le délai entre ouverture et résolution est le
   **MTTR**.
7. **Mesure** — le NOC relit ces tickets pour le suivi des **SLA**, les
   indicateurs d'incidents et le **rapport mensuel**.

Le NOC ne crée, n'acquitte ni ne résout rien : **toutes ses données viennent
des API des outils**. Une panne qu'aucune sonde ne voit doit faire l'objet
d'un ticket dans iTop, d'où elle remontera comme les autres.

Si la coupure était **programmée**, elle aura été déclarée comme
**changement** dans iTop (ou maintenance dans Zabbix) : l'alerte reste
visible mais marquée, et n'est pas comptée comme une panne dans les
indicateurs.

## Glossaire

| Terme | Signification |
|---|---|
| **ANPTIC** | L'agence qui exploite le réseau et ses outils. |
| **RESINA** | Le réseau informatique de l'administration. |
| **NOC** | *Network Operations Center* — la salle de supervision, et par extension cette plateforme. |
| **Outil source** | Un outil de supervision que la plateforme lit (Zabbix, Centreon, iTop, NetXMS, Nagios, NSP). |
| **Connecteur** | Le module de code qui sait lire un outil source (`integrations/`). |
| **Collecteur** | Le service qui lit tous les outils toutes les 5 minutes (`collector/`). |
| **Instantané** | L'état complet du parc et des alertes à un instant, écrit dans Redis par le collecteur. |
| **Équipement** (ou nœud) | Un appareil supervisé : routeur, switch, serveur, point d'accès… |
| **Fusion** | Le rapprochement d'un même équipement vu par plusieurs outils. |
| **Site** | Le lieu où se trouve un équipement (« DREP Gaoua », « ANPTIC Fada-Ngourma »). |
| **Alerte** | Un problème actif remonté par un outil source. Identifiée par `<outil>:<référence>`, par ex. `netxms:5647364`. |
| **Incident** | Un ticket **iTop** (classes `Incident`, `UserRequest`). Le NOC ne fabrique pas d'incident à partir d'une alerte. |
| **Gravité** | Critique, majeure, moyenne, mineure, information, inconnue — le vocabulaire commun à tous les outils. |
| **Acquitter** | Signaler, dans l'outil source, qu'on a pris connaissance d'une alerte. Le NOC affiche l'acquittement, il ne le fait pas. |
| **MTTO** | *Mean Time To Own* — délai moyen entre l'ouverture d'un ticket iTop et son affectation. |
| **MTTR** | *Mean Time To Resolve* — délai moyen entre l'ouverture d'un ticket iTop et sa résolution. |
| **SLA** | *Service Level Agreement* — engagements mesurés par les délais cibles TTA/TTR et par gravité. La disponibilité réseau est un KPI, mais n'est pas évaluée comme une cible SLA configurable. |
| **Maintenance planifiée** | Un changement iTop (ou une maintenance Zabbix) avec ses dates et ses CI : pendant la fenêtre, les équipements visés passent en « maintenance », leurs alertes sont marquées et exclues des indicateurs. Elle se planifie dans iTop, pas dans le NOC. |
| **Intervention** | Un ordre de travail iTop, rattaché au ticket qui le motive (équipe, agent, dates). Il s'affecte et se clôture dans iTop. |
| **CMDB** | Base de gestion des configurations : l'inventaire de référence (iTop). |
| **ITSM** | Gestion des services informatiques : les tickets (iTop). |
| **Dump / export** | Une copie de données de production (base NetXMS, journal Centreon), utilisée **en local seulement** pour visualiser des données réelles. En production, tout vient des API. |
| **Profil Docker Compose** | Un groupe de services optionnels lancés à la demande (`--profile netxms`, `--profile tools`…). |

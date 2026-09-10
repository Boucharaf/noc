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

1. **lit** tous les outils à intervalle régulier (toutes les 5 minutes) ;
2. **traduit** leurs données dans un vocabulaire commun (une gravité
   « critique » veut dire la même chose partout) ;
3. **fusionne** les équipements vus par plusieurs outils en un seul parc ;
4. **affiche** l'état du réseau, les alertes et les indicateurs, avec un écran
   adapté à chaque métier ;
5. **permet de traiter** les alertes : acquitter, affecter à un technicien,
   escalader, noter la cause, résoudre ;
6. **prévient** l'équipe d'une alerte grave par courriel, SMS ou notification
   navigateur ;
7. **mesure** le service rendu : disponibilité, délais de prise en charge et
   de résolution (MTTA, MTTR), respect des engagements (SLA), rapports
   mensuels.

Ce qu'elle **ne fait pas**, délibérément : elle ne remplace pas les outils de
supervision, n'installe pas de sondes, et **ne recopie pas leurs données**.
Elle lit, elle agrège, elle trace le travail de l'équipe. Le chapitre
[Architecture](02-architecture.md) explique pourquoi.

## Les utilisateurs et leurs écrans

Le besoin a été exprimé par l'agence dans le document *« informations
essentielles par profil »* (à la racine du dépôt), qui définit **quatre
niveaux de lecture**. Chacun correspond à un rôle et à un écran d'accueil.

| Niveau | Rôle | Écran d'accueil | Ce qu'il y cherche |
|---|---|---|---|
| 1 — Décideur | **Directeur** | `/direction` — Pilotage | Disponibilité globale, incidents critiques, SLA, MTTR, top 10 des sites, tendances, rapports. **Aucun geste d'exploitation.** |
| 2 — Chef NOC | **Chef NOC** | `/supervision` — Salle de supervision | État du réseau, alertes en cours, charge de chaque intervenant, santé de la collecte, équipements hors service, maintenances. **Gère aussi les comptes.** |
| 3 — Agent NOC | **Technicien** | `/console` — Console d'exploitation | La file des alertes à traiter, les sites touchés, les actions en cours. |
| 4 — Terrain | **Agent terrain** | `/terrain` — Tournée | Ses interventions sur site, les comptes rendus, le signalement d'une panne qu'aucune sonde ne voit. |

À côté des écrans d'accueil, des **écrans transverses** sont partagés selon
les droits :

| Écran | Adresse | Contenu |
|---|---|---|
| Incidents | `/incidents` | Le mur de toutes les alertes, filtrable |
| Équipements | `/equipements` | L'inventaire fusionné, et la fiche de chaque équipement |
| Carte des sites | `/carte` | Les sites et leur état |
| Performance réseau | `/performance` | Courbes de latence, pertes, trafic |
| SLA & disponibilité | `/sla` | Respect des engagements de service |
| Rapports | `/rapports` | Rapport mensuel PDF / DOCX |
| Maintenances | `/maintenances` | Fenêtres de coupure programmée |
| Collecte ETL | `/integrations` | L'état de la lecture de chaque outil |
| Utilisateurs | `/utilisateurs` | Gestion des comptes (Chef NOC) |
| Mon compte | `/compte` | Ses identifiants et préférences |
| Mur d'écrans | `/mur` | Affichage plein écran pour la salle |

## Le cycle de vie d'une panne

Voici ce qui se passe, de bout en bout, quand un routeur tombe :

1. **Détection** — la sonde de Zabbix (ou NetXMS, Centreon…) constate que le
   routeur ne répond plus et ouvre un *problème* dans l'outil.
2. **Collecte** — au plus 5 minutes plus tard, le collecteur du NOC lit
   l'outil, voit une alerte qui n'existait pas au cycle précédent.
3. **Diffusion** — l'alerte apparaît immédiatement sur tous les écrans ouverts
   (WebSocket), et si elle est critique ou majeure, un courriel part vers les
   personnes abonnées.
4. **Prise en charge** — un technicien l'**acquitte** (« je m'en occupe »). Le
   délai entre détection et acquittement est le **MTTA**.
5. **Répartition** — le Chef NOC l'**affecte** à un intervenant, voire
   programme une **intervention terrain**.
6. **Résolution** — une fois réparée, le technicien la **résout** en indiquant
   la **cause** (coupure électrique, fibre sectionnée…). Le délai entre
   détection et résolution est le **MTTR**.
7. **Mesure** — ces délais alimentent le suivi des **SLA** et le **rapport
   mensuel**. La cause saisie est la donnée la plus précieuse : aucun outil de
   supervision ne la connaît.

Si la coupure était **programmée**, le Chef NOC aura déclaré une **fenêtre de
maintenance** : l'alerte reste visible mais marquée, et n'est pas comptée
comme une panne dans les indicateurs.

Si la panne n'est vue par **aucune sonde** (site non supervisé, groupe
électrogène en panne), un agent la **signale à la main** : elle entre dans le
même circuit.

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
| **Incident** | Mot utilisé par les écrans pour une alerte en cours de traitement. Dans le code, les deux désignent la même chose. |
| **Incident manuel** | Une panne signalée à la main, qu'aucune sonde ne voit. Clé `manual:<n>`. |
| **Gravité** | Critique, majeure, moyenne, mineure, information, inconnue — le vocabulaire commun à tous les outils. |
| **Acquitter** | Signaler qu'on a pris connaissance d'une alerte et qu'on s'en occupe. |
| **Escalader** | Passer une alerte à un niveau supérieur (dans cette version : l'affecter à quelqu'un d'autre avec un motif). |
| **MTTA** | *Mean Time To Acknowledge* — délai moyen entre détection et acquittement. |
| **MTTR** | *Mean Time To Resolve* — délai moyen entre détection et résolution. |
| **SLA** | *Service Level Agreement* — engagement de service : délais cibles par gravité, disponibilité minimale. |
| **Fenêtre de maintenance** | Période de coupure programmée sur un équipement ou un site ; les alertes y sont marquées et exclues des indicateurs. |
| **Intervention** | Un déplacement d'agent terrain sur un site, avec statut (programmée, en route, sur site, terminée) et compte rendu. |
| **CMDB** | Base de gestion des configurations : l'inventaire de référence (iTop). |
| **ITSM** | Gestion des services informatiques : les tickets (iTop). |
| **Dump** | Une copie complète d'une base de données, sous forme de fichier SQL. |
| **Profil Docker Compose** | Un groupe de services optionnels lancés à la demande (`--profile netxms`, `--profile tools`…). |

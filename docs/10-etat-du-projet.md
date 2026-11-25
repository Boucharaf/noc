# 10. État du projet

> État au **24 novembre 2026**. À tenir à jour à chaque évolution notable :
> c'est le premier document qu'une équipe qui reprend le projet doit lire pour
> ne pas tomber dans les mêmes pièges.

## Ce qui fonctionne et a été vérifié

| Fonction | Vérification |
|---|---|
| **Suite backend** : connecteurs, fusion, cycle de collecte, agrégats journaliers, indicateurs, SLA et incidents iTop, limitation de débit, rapport mensuel | 275 tests réussis (24 novembre 2026) |
| **Qualité des données** : normalisation, fusion, erreurs de source et couverture de collecte ; les erreurs d'historique ne sont pas converties en séries vides | Tests `test_data_quality.py` |
| **Disponibilité** : les maintenances planifiées sont exclues du dénominateur ; un état inconnu ou muet n'est pas compté disponible | Tests des services temps réel et des agrégats journaliers |
| **Sessions** : rotation atomique, doublon concurrent, rejeu et révocations | Tests unitaires et vérification des scripts Lua sur un Redis temporaire réel |
| **SLA** : seuls les objectifs TTA/TTR sont modifiables ; respect mesuré sur les tickets iTop | Tests backend ciblés |
| **Journal d'audit** : connexions, comptes et objectifs SLA tracés, sans secret ; une écriture en échec n'annule pas l'action | `test_audit.py` |
| **Rapport mensuel** : bornes du mois transmises à iTop, rapport produit même si iTop est indisponible, rendu PDF et DOCX | `test_report_service.py` |
| **NetXMS par l'API** : formes de réponse tolérées, localité d'après la ville ou les coordonnées, alarmes d'interface rattachées, inventaire, interfaces, disponibilité de l'agence | `test_netxms_api.py` (réponses simulées, pas d'instance réelle) |
| **Données des API jusque-là ignorées** : contexte Zabbix (tags, cause, commentaires), inventaire, fusion des faits par outil, liens, contrat iTop (SLT) | `test_source_facts.py` |
| **Notifications** : envoi échoué retenté avec délais croissants, SMS retenté pour les seuls numéros en échec, abandon (alerte close, trop ancienne, tentatives épuisées) signalé par `/api/health` | `test_notification_retry.py`, `test_health.py` |
| **Résilience** : premier démarrage silencieux mais réseau sans alerte notifié, alertes nées pendant une coupure notifiées au retour, rafale en un message, compteurs du bilan repris au redémarrage, écriture du bilan réessayée | `test_resilience.py` |
| **Recette locale des connecteurs** (dump NetXMS, Zabbix de laboratoire, iTop de test, export Centreon) | `python -m collector.probe`, 29 octobre 2026 — chapitre 9 |
| **Journal historique** : périodes d'état et alertes, outil muet sans effet, trou d'observation jamais compté disponible, bilan journalier recalculé, échec d'écriture sans effet sur le cycle | `test_history.py` ; essai de bout en bout sur PostgreSQL 18 |
| **Sauvegarde** : quotidienne, restaurée à blanc, copie hors serveur vérifiée, pannes (base injoignable, fichier corrompu, partage démonté) | Exécutée dans son conteneur sur la base locale, restauration complète comprise |
| **Acquittements** : premier acquittement, changements d'une alerte, MTTA sur 30 jours alertes closes comprises | `test_history.py` ; essai sur PostgreSQL 16 |
| **Identité stable** : renommage, adresse, outil ajouté ou retiré, hôte recréé, réunion, séparation, base indisponible | `test_identity.py` ; copie de la base locale : 1 367 équipements et 152 765 pannes inchangés |
| **Santé des outils, rapports figés, conservation** | `test_retention_and_archive.py` ; copie de la base locale (refus de modification, purge, sauvegarde). Écrans non vérifiés dans un navigateur |
| **Export du journal Centreon** : rejeu des états HARD, acquittements, adresse IP, rejet d'un fichier d'une autre forme | `test_centreon_logs.py` |
| **Sécurité des tests d'intégration** : refus d'exécuter le script historique sans URL PostgreSQL dédiée terminant par `_test` ou `_tests` | Test du garde-fou ; le script complet n'a pas été exécuté sur une base |
| **Construction** : configuration Compose, images backend/collecteur, build et lint frontend | Commandes Docker Compose et npm réussies |

Ces contrôles sont des tests automatisés ciblés, pas une recette de bout en
bout sur les outils de production de l'agence.

## Rapport de test de l'agence (22-23 novembre 2026)

Anomalies concernant le NOC, corrigées le 24 novembre 2026 et vérifiées dans
un navigateur sur une pile isolée : A02 (PIN), A03 (blocage à 5 échecs), A05
(descriptif des rôles), A09 (PDF), A10 (export), A15 (dates), A16 (téléphone),
A18 (pluriels), A19 (menu, en-tête), changement du mot de passe provisoire,
adresse réelle des postes, mur d'écran (« indisponible » au lieu de « 0 »).

Restent : A06 (accès à iTop, agence), A07 (proxy frontal de la recette :
WebSockets à vérifier), A08 (compteurs à recompter sur la recette).

## Disponibilité : alignement sur la feuille « KPI NOC référence » (24 novembre 2026)

INC-01, INC-42, AM-29, KPI-01, KPI-02 et KPI-26 étaient marqués « Livré » sans
l'être entièrement. Corrigé : dégradé = disponible, horizon des sources figées
(le dump NetXMS du 7 août ne décide plus du présent), parc en service nommé
comme tel sur tous les écrans, score Santé sur la disponibilité, mois pondéré
par le temps supervisé, seuils cœur / accès / parc, collecte à 1 min. Une panne
coupée par un arrêt du collecteur n'est plus comptée deux fois. Bilans
recalculés depuis le 21 novembre. Restent à valider : les seuils et la règle
« cœur » (direction), la cadence de 1 min sur les outils de production (agence).

## Limites connues et dette technique

### 1. Recette d'intégration à compléter

- Le script `backend/tests/test_integration.py` écrit et supprime des données
  dans un schéma historique (`dim_*`, `fact_*`) ; son garde-fou protège les
  bases non dédiées, mais le scénario doit être réécrit pour le schéma actuel.
- Les connecteurs **Nagios et Nokia NSP** n'ont pas été validés sur des
  instances réelles. Nagios est validé sur son laboratoire (profil
  `nagios`) ; NSP l'est seulement contre un simulateur écrit d'après le
  connecteur (`tools/nsp-sim`, 29 octobre 2026), ce qui ne prouve rien sur
  l'instance de l'agence. Les modes `NAGIOS_MODE` et `NSP_FM_MODE` sont à confirmer
  avec l'agence.
- Les tests backend disponibles ne remplacent pas une recette avec les vraies
  versions des outils, leurs permissions de lecture seule et les données de
  l'agence.

### 2. Historique et indicateurs

- `kpi_daily` se remplit à partir des cycles du collecteur ; il ne reconstitue
  pas les jours antérieurs à son démarrage. Les anciens agrégats ne sont pas
  recalculés automatiquement après le changement de règle de maintenance.
- Si la lecture des fenêtres de maintenance échoue ou dépasse le délai, le
  collecteur omet l'échantillon journalier concerné et le signale plutôt que
  de calculer une disponibilité en supposant à tort qu'il n'y a aucune
  maintenance.
- Les courbes réseau sont calculées sur un échantillon plafonné à 50
  équipements. L'API et l'interface indiquent les tailles de population,
  d'échantillon et de contribution ainsi que les erreurs de sources.
- Les coordonnées cartographiques et les organisations dépendent des données
  publiées par les sources. La disponibilité « par ministère » est désormais
  lue par organisation des CI iTop (`/organisations`, vue Direction).
- **Toutes les données viennent des API des outils.** Le signalement manuel
  d'incident a été retiré (28 octobre 2026), ainsi que les tables qui n'étaient
  plus alimentées : `ops_alert_state`, `ops_alert_timeline`,
  `ops_manual_incident`, `ops_maintenance_window`, `ops_field_intervention`.
  Elles sont supprimées en rejouant `backend/sql/schema.sql` (ou par la
  migration Alembic `0004`) ; leur contenu n'est pas conservé.
- **Disponibilité des liens** : calculée sur l'état réel des interfaces
  NetXMS (écran Performance réseau). Dans le dump, NetXMS n'« attend
  actives » que peu d'interfaces (54 équipements) ; la part des interfaces
  activées qui transmettent est donnée à côté, ports libres compris.
- **Taux d'utilisation de la bande passante** : non calculé. Le débit nominal
  des interfaces est connu (NetXMS), mais pas leur trafic dans le même cycle :
  il faudrait lire les mesures de trafic de chaque interface, ce que le
  collecteur ne fait pas pour ne pas charger les outils.
- **Journal historique** (29 octobre 2026) : disponibilité par équipement et
  par lien sur la durée, pannes, MTTR technique, rattrapage des bilans
  journaliers. Il ne couvre que la période depuis sa mise en service. Les
  liens suivis un par un sont ceux que NetXMS attend actifs (54 équipements
  dans le dump). Vérifié sur PostgreSQL 16 et 18, pas encore en production.
- **Identité** (24 novembre 2026) : l'identifiant d'un équipement ne change
  plus. Restent : nom et adresse changés ensemble (nouvel équipement, à
  rattacher par `attach`) ; l'historique d'un **lien** recommence si l'outil
  recrée l'interface.
- **Acquittements** : une alerte acquittée puis close entre deux cycles n'est
  pas vue acquittée. Nagios : date à un cycle près. L'auteur n'est connu que
  pour Zabbix, Centreon (API) et iTop.
- **Rapports figés** : le PDF reprend le rapport mensuel ; MTTA et santé des
  outils ne sont que dans les données jointes. Les **tickets iTop** ne sont pas
  copiés un par un. Figement automatique coupé (`REPORT_FREEZE_ENABLED=false`)
  tant que les données viennent du dump.
- **Trous de collecte** : le collecteur tourne sur un poste, pas sur un
  serveur. Bilans présents : mai (23 j), juin (30), juillet (31), août (7) et
  novembre 2026 (3) ; septembre et octobre sont vides.
- **Mesures longue durée (`metric_hourly`) : non faites.** Les mesures NetXMS
  ne sont pas dans le dump (hypertables TimescaleDB). L'agence les garde
  30 jours pour 92 % des métriques actives : sans copie, aucune comparaison
  annuelle. Prévu : min, moyenne, max par heure (13 mois) et par jour (10 ans),
  dans une base séparée ; environ 36 600 métriques, 27 Go par an. Bloqué par
  l'accès aux mesures.
- Incidents réouverts : iTop ne compte pas les réouvertures. Est compté
  « réouvert » un ticket qui porte une date de résolution sans être résolu ni
  clos, donc rouvert et pas encore résolu à nouveau.
- La cible de disponibilité réseau n'est pas un SLA mesuré. Seules les cibles
  TTA/TTR sont configurables et évaluées.

### 3. Sources figées et notifications

- **Production par les API seules** : le NOC fonctionne sans dump ni base
  d'outil. Deux connecteurs n'ont toutefois jamais rencontré l'instance de
  l'agence : **NetXMS par son API** et **Nokia NSP**. À la mise en service,
  `python -m collector.probe` doit confirmer qu'ils lisent équipements,
  alertes et localités. Par l'API, NetXMS ne donne pas le site administratif
  de l'agence : le site devient la ville, sauf attribut personnalisé
  (`NETXMS_SITE_ATTRIBUTE`).
- Le dump NetXMS est une photographie arrêtée au **7 août 2026**, l'export
  du journal Centreon au **27 octobre 2026** : ni l'un ni l'autre ne produit
  de nouvelles alertes. L'export Centreon fourni ne contient que des états OK
  (aucune alerte) ; un export sans filtre de statut serait nécessaire pour en
  voir.
- **Outils de laboratoire** : Zabbix redémarre avec Docker depuis le
  24 novembre 2026 (environ 1 Go de mémoire), comme Nagios, NSP et NetXMS.
  iTop et Centreon n'ont pas de redémarrage automatique.
- **iTop de test de l'agence** : lu le 29 octobre 2026, injoignable le
  24 novembre. Le nom se résout et les ports 80 et 443 sont ouverts, mais le
  serveur refuse ce nom en TLS (`unrecognized_name`) et répond 403 en HTTP.
  À régler avec l'agence. D'ici là : ni tickets, ni SLA, ni maintenances iTop.
- Les 71 alarmes orphelines identifiées lors de l'inspection du dump NetXMS
  ne sont pas rattachées à des équipements ou interfaces connus ; elles
  apparaissent dans *Collecte ETL* → « Alertes sans équipement ».
- Une notification sortante échouée est **retentée** (1, 5, 15, 30, 60 min,
  6 tentatives, alerte active de moins de 6 h), puis abandonnée et signalée
  par `/api/health`.
- **Notifications navigateur (Web Push)** : l'abonnement s'enregistre dans
  *Mon compte*, mais aucun envoi n'est déclenché sur alerte
  (`push_service` n'est appelé nulle part). Seuls le courriel et le SMS
  partent.
- **Notifications après une coupure** (corrigé le 29 octobre 2026) : la
  mémoire des alertes vues n'expire plus ; les pannes apparues pendant une
  coupure du collecteur sont notifiées au retour, en un message
  récapitulatif au-delà de 10. Un défaut plus grave a été corrigé au passage :
  un cycle sans aucune alerte effaçait cette mémoire, et la panne suivante
  n'était alors **jamais notifiée**.
- Seul un vrai premier démarrage (Redis neuf ou vidé) ne notifie rien. Vider
  Redis en exploitation fait donc perdre les notifications du premier
  cycle.

### 4. Déploiement et sécurité opérationnelle

- Le durcissement réseau, API et authentification est décrit au
  [chapitre 5](05-comptes-roles-securite.md#durcissement-en-place). Une
  recette de production reste nécessaire : certificat de l'agence, secrets
  propres à l'environnement et exposition réseau limitée.
- **Identifiants de production exposés** : les commits `2d1131d` et `8fdf1d9`
  de l'historique git contiennent, dans `.env.example`, le mot de passe et le
  jeton d'API du Zabbix de l'agence ainsi que le compte iTop. Ils doivent être
  **changés chez l'agence** ; les retirer de l'historique ne suffit pas, le
  dépôt ayant été publié.
- Le certificat est auto-signé, émis pour `noc.anptic.bf` et `localhost`.
- La limitation de débit de l'API est un middleware global (`app/main.py`),
  actif par défaut : quota par IP et quota par utilisateur authentifié, sur
  toutes les routes `/api/`. Si Redis est indisponible, la requête passe
  (choix assumé : la disponibilité du tableau de bord prime). Les dépendances
  par route `read_rate_limit` / `write_rate_limit` ne sont branchées nulle
  part et font doublon avec ce middleware. `X-Real-IP` n'est pris en compte
  que depuis l'adresse nginx autorisée sur le réseau privé dédié.
- Agrégats journaliers : compteurs du jour sauvegardés dans Redis à chaque
  cycle, écriture réessayée toutes les 15 minutes en cas d'échec, puis
  recalcul depuis le journal historique en dernier recours (chapitre 9).
- `INTERNAL_API_KEY` et certains scripts d'inspection de l'ancien schéma
  demeurent dans le dépôt ; ils ne font pas partie du chemin actif de collecte.

## Prochaines étapes suggérées

1. **Réécrire le test d'intégration historique** avec les modèles et routes
   actuels, puis l'exécuter exclusivement sur une base dédiée.
2. **Faire une recette sur la VM de test de l'agence**, avec comptes sources
   en lecture seule et vérification de la fraîcheur, de la couverture et des
   erreurs de chaque connecteur.
3. **Valider NetXMS par son API, Nagios et Nokia NSP** sur les versions
   réellement exploitées (`python -m collector.probe`) et confirmer leurs
   modes de connexion.
4. **Ajuster les quotas de débit** à l'usage réel (opérateurs partageant
   une même adresse IP derrière un NAT) et retirer les dépendances par route
   inutilisées.
5. **Compléter les données géographiques et d'organisation** dans les outils
   sources (l'agrégat par organisation n'est juste que si les CI iTop en
   portent une).
6. **Importer le modèle Zabbix** `monitoring/zabbix/noc_resina_by_http.yaml`
   dans le Zabbix de l'agence et vérifier ses déclencheurs (chapitre 9).
7. **Brancher ou retirer les notifications navigateur.**
8. **Obtenir de l'agence** : l'accès à iTop, un export de mesures NetXMS de
   7 jours puis un compte en lecture seule, la durée légale de conservation,
   un serveur permanent (100 Go pour les mesures), un partage pour les
   sauvegardes (`BACKUP_OFFSITE_DIR`).
9. **Afficher l'identité** (références, décisions) sur la fiche d'équipement :
   l'API la rend, aucun écran ne la montre.
10. **Corriger les constats de la recette locale** (chapitre 9, « Recette des
   connecteurs ») : IP des hôtes Zabbix supervisés par nom DNS, tickets iTop
   sans CI rattaché, alertes NetXMS sans équipement.

# 10. État du projet

> État au **29 octobre 2026**. À tenir à jour à chaque évolution notable :
> c'est le premier document qu'une équipe qui reprend le projet doit lire pour
> ne pas tomber dans les mêmes pièges.

## Ce qui fonctionne et a été vérifié

| Fonction | Vérification |
|---|---|
| **Suite backend** : connecteurs, fusion, cycle de collecte, agrégats journaliers, indicateurs, SLA et incidents iTop, limitation de débit, rapport mensuel | 145 tests réussis (29 octobre 2026), réalignés sur l'architecture actuelle |
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
| **Export du journal Centreon** : rejeu des états HARD, acquittements, adresse IP, rejet d'un fichier d'une autre forme | `test_centreon_logs.py` |
| **Sécurité des tests d'intégration** : refus d'exécuter le script historique sans URL PostgreSQL dédiée terminant par `_test` ou `_tests` | Test du garde-fou ; le script complet n'a pas été exécuté sur une base |
| **Construction** : configuration Compose, images backend/collecteur, build et lint frontend | Commandes Docker Compose et npm réussies |

Ces contrôles sont des tests automatisés ciblés, pas une recette de bout en
bout sur les outils de production de l'agence.

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
  dans le dump). Un équipement dont l'identifiant de fusion change (nouvel
  outil qui le voit) recommence un historique sous son nouvel identifiant.
  Vérifié sur PostgreSQL 18 (essai de bout en bout), pas encore en
  production.
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
8. **Corriger les constats de la recette locale** (chapitre 9, « Recette des
   connecteurs ») : IP des hôtes Zabbix supervisés par nom DNS, tickets iTop
   sans CI rattaché, alertes NetXMS sans équipement.

# 10. État du projet

> État au **9 octobre 2026**. À tenir à jour à chaque évolution notable :
> c'est le premier document qu'une équipe qui reprend le projet doit lire pour
> ne pas tomber dans les mêmes pièges.

## Ce qui fonctionne et a été vérifié

| Fonction | Vérification |
|---|---|
| **Qualité des données** : normalisation, fusion, erreurs de source et couverture de collecte ; les erreurs d'historique ne sont pas converties en séries vides | Suite backend ciblée : 16 tests réussis dans Docker |
| **Disponibilité** : les maintenances planifiées sont exclues du dénominateur ; un état inconnu ou muet n'est pas compté disponible | Tests des services temps réel et des agrégats journaliers |
| **Sessions** : rotation atomique, doublon concurrent, rejeu et révocations | Tests unitaires et vérification des scripts Lua sur un Redis temporaire réel |
| **Droits terrain et SLA** : signalement limité au site affecté d'un agent terrain ; seuls les objectifs TTA/TTR mesurés sont modifiables | Tests backend ciblés |
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
  instances réelles. Les modes `NAGIOS_MODE` et `NSP_FM_MODE` sont à confirmer
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
  publiées par les sources. L'agrégat « par ministère » de l'ancienne version
  n'est plus alimenté ; l'interface peut donc afficher cette section vide.
- La cible de disponibilité réseau n'est pas un SLA mesuré. Seules les cibles
  TTA/TTR sont configurables et évaluées.

### 3. Sources figées et notifications

- Le dump NetXMS est une photographie arrêtée au **7 août 2026** : il ne
  contient pas de nouvelles alertes après cette date. Les 71 alarmes orphelines
  identifiées lors de l'inspection du dump ne sont pas rattachées à des
  équipements ou interfaces connus.
- Une notification sortante échouée est journalisée mais **n'est pas retentée**.
- Au démarrage du collecteur, les alertes déjà présentes ne sont pas
  renotifiées : cela évite un envoi massif lors d'une reprise.

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
- Le composant de limitation générique de l'API existe, mais ses dépendances
  ne sont pas branchées aux routes : les quotas configurés ne protègent donc
  pas encore les appels API. La connexion reste protégée par ses compteurs
  d'échecs et par la limitation nginx dédiée. `X-Real-IP` n'est pris en
  compte que depuis l'adresse nginx autorisée sur le réseau privé dédié.
- `INTERNAL_API_KEY` et certains scripts d'inspection de l'ancien schéma
  demeurent dans le dépôt ; ils ne font pas partie du chemin actif de collecte.

## Prochaines étapes suggérées

1. **Réécrire le test d'intégration historique** avec les modèles et routes
   actuels, puis l'exécuter exclusivement sur une base dédiée.
2. **Faire une recette sur la VM de test de l'agence**, avec comptes sources
   en lecture seule et vérification de la fraîcheur, de la couverture et des
   erreurs de chaque connecteur.
3. **Valider Nagios et Nokia NSP** sur les versions réellement exploitées et
   confirmer leurs modes de connexion.
4. **Brancher et tester la limitation générique de débit** sur les routes
   pertinentes, en tenant compte des opérateurs partageant une même adresse
   IP.
5. **Compléter les données géographiques et d'organisation** dans les outils
   sources ; décider si un agrégat par organisation doit remplacer l'ancien
   classement par ministère.
6. **Définir une politique de reprise des notifications échouées**, sans
   compromettre la déduplication actuelle.

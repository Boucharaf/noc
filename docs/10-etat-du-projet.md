# 10. État du projet

> État au **10 septembre 2026**. À tenir à jour à chaque évolution notable :
> c'est le premier document qu'une équipe qui reprend le projet doit lire pour
> ne pas tomber dans les mêmes pièges.

## Ce qui fonctionne et a été vérifié

| Fonction | Vérification |
|---|---|
| **Comptes et rôles** : création réservée au Chef NOC, attribution des rôles, auto-modification des identifiants sans le rôle, garde-fous (auto-rétrogradation, identifiant déjà pris, mot de passe requis), réinitialisation, coupure des sessions | Recette automatisée de 30 contrôles sur l'API |
| **Alertes par courriel** : abonnés + listes fixes, test depuis l'interface, alerte temps réel reçue une seule fois malgré deux backends, incident manuel grave notifié, gravité moyenne ignorée, contenu échappé, journalisation | Recette de bout en bout avec Mailpit |
| **NetXMS par la base** : 1 409 équipements, 791 alarmes, sites issus du référentiel de l'agence (1 255 équipements situés), compte de lecture confiné (secrets refusés, écriture impossible) | Sur le dump de production restauré |
| **Fusion des équipements** : pas de fusion sur une IP prise pour un nom, pas de fusion au sein d'un même outil | Test synthétique et données réelles |
| **Interface** : les 23 écrans s'affichent sans erreur pour les quatre rôles ; la fiche d'incident s'ouvre | Recette automatisée dans un navigateur (Edge) |

## Limites connues et dette technique

Classées par importance.

### 1. Couche de compatibilité du frontend

Les écrans ont été écrits pour l'ancienne API. Des adaptations dans
`frontend/src/hooks/queries.js` les font fonctionner (voir
[chapitre 8](08-frontend.md#la-couche-de-compatibilité--à-connaître-absolument)),
mais :

- certaines données **n'existent plus** et s'affichent vides ou « — » : carte
  des sites (pas de coordonnées dans l'instantané), agrégat par ministère,
  région, MTTR par site, date de mise hors service d'un équipement, bande « pire
  équipement » des courbes ;
- les **indicateurs réseau** (latence, pertes, CPU, trafic) ne s'affichent que
  si un outil de mesure (Zabbix, Centreon) est branché ;
- les **actions** de la fiche d'incident (acquitter, affecter, escalader,
  commenter, résoudre) passent par une traduction d'arguments qui n'a pas été
  testée en cliquant ;
- le **lien profond** vers une alerte (`/incidents?id=…`) attend encore un
  identifiant numérique ; les courriels pointent vers la liste des incidents.

**Cible** : réécrire chaque écran sur les hooks natifs, puis supprimer la
couche. Commencer par les écrans d'accueil.

### 2. Écarts de permissions entre interface et backend

L'interface montre des boutons que le backend refuse, ou l'inverse :

| Action | Interface | Backend |
|---|---|---|
| Acquitter une alerte | chef NOC, technicien, **agent terrain** | **directeur**, chef NOC, technicien |
| Créer une maintenance | directeur, chef NOC, **technicien** | directeur, chef NOC |
| Programmer une intervention | **agent terrain**, chef NOC, directeur | directeur, chef NOC, **technicien** |

Trancher la règle métier voulue, puis aligner `frontend/src/lib/permissions.js`
et les tuples de rôles des routes.

### 3. Pas de tests automatisés à jour

`backend/tests/test_integration.py` vise les tables de l'ancien entrepôt
(`dim_*`, `fact_*`) : il ne fonctionne plus. Aucun test frontend, aucune
intégration continue. Les recettes réalisées lors des dernières évolutions
(comptes, courriels, écrans) étaient des scripts ponctuels : les transformer en
tests permanents est la priorité pour sécuriser les évolutions.

### 4. Sécurité avant exposition réseau

- La base du NOC (`5436`) et le backend sont publiés sur toutes les interfaces.
- La limitation de débit (`backend/app/core/rate_limit.py`) n'est branchée sur
  aucune route.
- Le certificat est auto-signé, émis pour `noc.anptic.bf` et `localhost`.
- `INTERNAL_API_KEY` est un reste de l'ancienne ETL : aucune route ne l'utilise.

### 5. Données

- Le **dump NetXMS est figé** au 07/08/2026 : aucune alerte nouvelle, donc
  aucune notification automatique ; l'âge des alertes compte depuis cette date.
- **71 alarmes NetXMS restent orphelines** (portées par des objets qui ne sont
  ni des équipements ni des interfaces : services métier, conteneurs).
- `kpi_daily` est **vide au démarrage** : les tendances, le classement des sites
  et les taux SLA se remplissent au fil des jours d'exploitation.
- Les connecteurs **Nagios et NSP** n'ont jamais été testés ; `NAGIOS_MODE` et
  `NSP_FM_MODE` sont à confirmer auprès de l'agence.
- Un envoi de notification **échoué n'est pas retenté**.

### 6. Documentation et restes de l'ancienne version

- `frontend/README.md` décrit l'interface au moment de sa réécriture ; il cite
  des fonctions (ministères, régions) qui n'ont plus de source.
- `database/inspect_netxms_schema.py` et `database/netxms_inspect.sql` sont des
  outils d'inspection de l'ancienne approche, sans usage actuel.
- Certains commentaires du code parlent encore de `dim_user`, `fact_incident`
  ou du « veilleur » : ce sont des références à l'ancienne architecture.

## Prochaines étapes suggérées

1. **Déployer sur la machine virtuelle de test de l'agence**, idéalement avec
   des comptes en lecture seule sur les vrais outils plutôt que le dump.
2. **Fermer les ports internes** et brancher la limitation de débit.
3. **Aligner les permissions** interface / backend (point 2).
4. **Écrire les tests** : comptes et droits, notifications, connecteurs (sur
   des réponses enregistrées), fusion.
5. **Réécrire les écrans d'accueil** sur l'API native, en commençant par la
   salle de supervision et la console.
6. **Rétablir la carte** : source explicite de coordonnées (le référentiel de
   sites de l'agence en contient : `donnebase.siteadministratif` a une latitude
   et une longitude).
7. **Agrégat par ministère / organisation** côté backend (le référentiel de
   l'agence porte un champ `Ministère`, iTop porte l'organisation).

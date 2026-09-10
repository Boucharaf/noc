# Documentation de la plateforme NOC RESINA

Cette documentation s'adresse à **toute personne qui découvre le projet** :
chef de projet, développeur, exploitant, nouvelle équipe de maintenance. Elle
explique ce que fait la plateforme, comment elle est construite, et où
intervenir.

Pour **installer et lancer** la plateforme, voir le
[README à la racine](../README.md).

---

## Les chapitres

| # | Chapitre | Répond à la question |
|---|---|---|
| 1 | [Comprendre le projet](01-comprendre-le-projet.md) | À quoi sert la plateforme, pour qui, et avec quel vocabulaire ? |
| 2 | [Architecture](02-architecture.md) | Quels sont les composants, et comment circule une donnée ? |
| 3 | [Organisation du code](03-organisation-du-code.md) | Où se trouve quoi dans le dépôt, et où modifier pour faire X ? |
| 4 | [Sources de données](04-sources-de-donnees.md) | Comment la plateforme lit Zabbix, Centreon, iTop, NetXMS… et fusionne leurs équipements ? |
| 5 | [Comptes, rôles et sécurité](05-comptes-roles-securite.md) | Qui a le droit de faire quoi, et comment l'accès est protégé ? |
| 6 | [Alertes et notifications](06-alertes-et-notifications.md) | Quand et comment un incident est-il signalé par courriel ou SMS ? |
| 7 | [Backend (API)](07-backend.md) | Comment est construite l'API, quelles routes, quelle base de données ? |
| 8 | [Frontend (interface)](08-frontend.md) | Comment est construite l'interface, et comment ajouter un écran ? |
| 9 | [Exploitation et dépannage](09-exploitation.md) | Comment faire tourner, surveiller, sauvegarder et réparer la plateforme ? |
| 10 | [État du projet](10-etat-du-projet.md) | Qu'est-ce qui marche, qu'est-ce qui reste à faire, quelles limites connaître ? |

Deux documents historiques restent à la racine et sont cités par les
chapitres : [ARCHITECTURE.md](../ARCHITECTURE.md) (le raisonnement complet
derrière l'architecture) et [tools/README.md](../tools/README.md) (les outils
de laboratoire).

---

## Par où commencer ?

**Vous découvrez le projet (tout profil)** — 30 minutes :
1 → 2 → 10. Vous saurez ce que fait la plateforme, comment elle tient
debout, et ce qui n'est pas terminé.

**Vous allez développer** :
1 → 2 → 3, puis 7 (backend) ou 8 (frontend), puis 4 si vous touchez aux
outils de supervision. Lire le chapitre 10 avant de commencer : il liste les
pièges et la dette technique.

**Vous allez exploiter la plateforme (installation, supervision, support)** :
le [README](../README.md), puis 9 → 5 → 6.

**Vous devez présenter le projet à l'agence ou à l'équipe sécurité** :
1 → 2 (section « Principes ») → 5 → 4 (section « Garanties envers la
production »).

---

## Conventions de cette documentation

- Les chemins de fichiers sont relatifs à la racine du dépôt.
- Les commandes sont écrites pour **bash** (Git Bash sous Windows).
- « L'agence » désigne l'ANPTIC, qui exploite le réseau RESINA et ses outils
  de supervision de production.
- Le code source est lui-même abondamment commenté, en français, en
  expliquant **pourquoi** plutôt que quoi. Quand un chapitre renvoie à un
  fichier, l'en-tête de ce fichier est la suite naturelle de la lecture.

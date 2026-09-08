# Frontend NOC RESINA — console de supervision

Interface **entièrement réécrite**. L'ancienne version n'a pas été
retouchée : elle a été remplacée, parce que ses défauts étaient
structurels et non cosmétiques.

---

## 1. Ce qui n'allait pas, et ce qui a changé

| Constat sur l'ancienne interface | Ce qui a été fait |
|---|---|
| La vue Chef NOC se retrouvait dans la vue Décideur : mêmes blocs, mêmes chiffres, seul le titre changeait | **Un écran par profil**, avec un contenu réellement distinct — le Directeur n'a aucun bouton d'action sur un incident, le Chef NOC est le seul à voir la charge par intervenant |
| Les informations affichées ne disaient pas ce qu'un exploitant a besoin de savoir | Reprise du document métier « informations essentielles par profil » : les quatre niveaux (Décideur / Chef NOC / Agent NOC / technique) sont désormais quatre écrans |
| Rien ne ressemblait à un NOC | Bandeau d'état permanent, ticker d'alertes, horloge à la seconde, mode mur d'écrans, densité de console (13 px, lignes de 28 px) |
| Le drill-down n'existait pas | Tout nom d'équipement, de site ou de ministère est cliquable, dans les deux sens : KPI global → ministère → site → équipement → incident |
| Aucun inventaire d'équipements | Écran **Équipements** complet, avec état dérivé (HS / dégradé / muet / maintenance / nominal) et fiche technique par équipement |
| Pas de création de compte | Écran **Utilisateurs** : création, rôle, périmètre, PIN, désactivation |

---

## 2. Les quatre profils et leurs écrans

Chaque rôle atterrit sur **son** tableau de bord après connexion. Les
écrans transverses sont partagés mais protégés par permission.

| Rôle | Écran d'accueil | Ce qu'il y trouve |
|---|---|---|
| **Directeur** | `/direction` | Niveau 1 — disponibilité globale, SLA, MTTR/MTTA, incidents critiques, tendance 6 mois, Top 10 sites, ministères, causes, carte, couverture, rapports PDF/DOCX. **Aucune action d'exploitation** : un directeur qui acquitte une alerte court-circuite la file du technicien |
| **Chef NOC** | `/supervision` | Niveau 2 — état du réseau, courbe agrégée avec bande « pire équipement », répartition du parc, **charge par intervenant** (ligne « non affecté » en tête), **santé de la collecte ETL**, maintenances en cours, sites les plus touchés |
| **Technicien** | `/console` | Niveau 3 — file de traitement en pleine largeur (À traiter / À moi / Tout), équipements hors service, constantes réseau, répartition des alertes. Tout se traite dans un tiroir sans quitter la file |
| **Agent terrain** | `/terrain` | Tournée du jour, changement d'état (je pars → sur site → compte rendu), relevé GPS, signalement de panne. Pensé pour un téléphone tenu d'une main |

**Écrans transverses** : `/incidents`, `/equipements` + `/equipements/:id`
(niveau 4), `/carte`, `/performance`, `/sla`, `/integrations`,
`/maintenances`, `/rapports`, `/utilisateurs`, `/compte`, `/mur`.

### Une contrainte d'API à connaître

Le rôle `agent_terrain` **n'a pas accès** à `GET /api/incidents` (403 —
voir `backend/app/routes/incidents.py::_VIEW_HISTORY`). L'écran terrain
lit donc les alertes via `/api/alerts/open`, ouverte à tout compte
connecté. Le détail d'un incident précis reste accessible, d'où le tiroir
de détail qui fonctionne aussi pour ce profil.

---

## 3. Parti pris visuel — et pourquoi

Ce n'est volontairement pas un dashboard SaaS. Quatre contraintes ont
dicté la forme :

**1. Un exploitant passe huit heures devant cet écran.** Le fond est
sombre **par défaut**, pas en option. La couleur saturée est réservée à
ce qui doit arracher le regard — une alerte critique, rien d'autre. Un
bouton bleu vif à côté d'un compteur d'incidents critiques rouge, et
l'œil ne sait plus où aller.

**2. La densité prime sur l'aération.** Base 13 px, lignes de tableau à
28 px : on veut 25 incidents à l'écran, pas 6 cartes arrondies. Angles
quasi droits (3 px), pas d'ombre portée — un panneau d'instrumentation,
pas une carte.

**3. Tous les chiffres sont en chasse fixe tabulaire.** Une colonne de
MTTR qui danse d'un pixel à chaque rafraîchissement est illisible en
vision périphérique, et la vision périphérique est le mode de lecture
normal d'un mur d'écrans.

**4. Rien ne bouge sans raison.** Les seules animations permanentes sont
le point « live » et le ticker d'alertes ; les deux portent une
information (le flux temps réel est vivant). Le clignotement est réservé
aux critiques **non acquittés** : dès que quelqu'un prend la main, la
ligne cesse de réclamer l'attention de toute la salle.
`prefers-reduced-motion` coupe tout.

### Trois règles d'affichage tenues partout

* **Une donnée absente s'écrit « — », jamais « 0 ».** Sur un écran
  d'exploitation, un zéro à la place d'une mesure manquante se lit
  « tout va bien » alors qu'il signifie « on ne sait pas ». Quand une
  métrique n'est pas collectée, la tuile le dit explicitement.
* **Un KPI est toujours affiché avec sa cible.** « MTTR : 5 h 20 » ne
  permet à personne de décider quoi que ce soit ; « 5 h 20, cible ≤ 4 h,
  +1 h 20 vs mois dernier » si.
* **Vide, en chargement et en erreur sont trois états distincts.**
  « Aucun incident critique » et « backend injoignable » produisent tous
  deux un tableau vide ; un NOC qui affiche le premier alors qu'il faut
  lire le second ne voit pas une panne majeure.

---

## 4. Temps réel

Un **seul** WebSocket pour toute l'application, ouvert par `AppShell` et
jamais par une page — sinon chaque navigation ouvrirait une connexion de
plus.

* Authentification par la **première trame** (`{"type":"auth","token":…}`)
  et non par `?token=` : un navigateur ne peut pas poser d'en-tête
  Authorization sur une poignée de main WebSocket, et un jeton dans l'URL
  finit en clair dans les journaux du reverse proxy.
* **Chien de garde 60 s** : le serveur envoie un ping toutes les 20 s.
  Sans trafic au-delà, la socket est déclarée morte même si le navigateur
  la croit ouverte — cas classique derrière un proxy qui a coupé le flux
  sans envoyer de FIN. Sans ce garde-fou, l'écran reste « connecté » et
  n'affiche plus rien.
* **Reconnexion en repli exponentiel** plafonné à 30 s.
* Le WebSocket n'est pas la seule source de vérité : le polling continue
  en parallèle. La socket sert à réagir dans la seconde, le poll garantit
  qu'un écran reste juste même si la socket est tombée sans qu'on s'en
  aperçoive.

Un **signal sonore** discret accompagne les alertes critiques. Il est
produit par l'AudioContext du navigateur (deux oscillateurs, 180 ms)
plutôt que par un fichier : pas d'asset, pas de préchargement, pas de
politique d'autoplay à contourner.

---

## 5. Cadences de rafraîchissement

Décidées requête par requête dans `hooks/queries.js`, parce que c'est une
décision d'exploitation et pas un détail de composant :

| Régime | Intervalle | Ce qu'il couvre |
|---|---|---|
| `LIVE` | 20 s | alertes, résumé, parc en panne. Le WebSocket pousse déjà les nouveautés ; ce poll est le filet de sécurité si la socket est tombée |
| `OPERATIONAL` | 60 s | files d'incidents, inventaire, interventions, interopérabilité |
| `ANALYTIC` | 5 min | KPI mensuels, SLA, tendances — exactement le `CACHE_TTL` du backend. Interroger plus souvent ne relirait que la même réponse Redis |

Le bouton **⏸ / ▶** de la barre supérieure coupe les trois : sur une
liaison de secours, un poll permanent coûte plus qu'il ne rapporte.

---

## 6. Sécurité côté client

Le RBAC de `lib/permissions.js` est du **confort d'interface**, jamais une
protection. La seule autorisation qui compte est le 403 renvoyé par le
backend. Chaque entrée du fichier est la copie exacte d'un tuple de rôles
déclaré dans une route, avec la référence en commentaire — une divergence
produit soit un bouton mort, soit une fonction cachée à quelqu'un qui y a
droit.

Le **jeton d'accès ne vit qu'en mémoire**, jamais en `localStorage` : un
XSS le lirait en une ligne. La session est restaurée au chargement par le
cookie httpOnly de rafraîchissement, auquel JavaScript n'a pas accès.

Le rafraîchissement est **sérialisé** : un dashboard lance 10 à 15
requêtes au montage, et si le jeton vient d'expirer elles échouent toutes
en 401 simultanément. Sans sérialisation, chacune déclencherait son propre
`/auth/refresh`, et la rotation du refresh token invaliderait tous les
appels sauf un — déconnectant un utilisateur dont la session est valide.

---

## 7. Structure

```
src/
├── api/
│   ├── client.js        # axios : jeton, corrélation, refresh sérialisé, 401/403
│   ├── config.js        # BASE_URL et URL du WebSocket
│   └── noc.js           # ⭐ contrat d'API — miroir de backend/app/routes/
├── lib/
│   ├── permissions.js   # matrice rôle → droits (copie des routes backend)
│   ├── vocabulary.js    # sévérités, statuts, états, métriques, outils
│   ├── format.js        # nombres, durées, dates — « — » pour l'absence
│   └── download.js      # export CSV / PDF avec détection d'erreur JSON
├── store/
│   ├── auth.js          # session (jeton en mémoire seule)
│   └── ui.js            # thème, densité, période, rafraîchissement
├── hooks/
│   ├── queries.js       # ⭐ toutes les requêtes + leurs cadences
│   ├── useRealtime.js   # WebSocket unique, chien de garde, reconnexion
│   ├── useSession.js    # bootstrap, keep-alive, thème, permissions
│   └── useClock.js      # horloge de salle, alignée sur la seconde
├── components/
│   ├── ui/              # Panel, Table, Stat, Badge, Controls, Overlay, States
│   ├── charts/          # Chart.js + sparkline/heatmap/donut en SVG
│   ├── layout/          # AppShell, TopBar, SideNav, StatusStrip, AlertTicker
│   └── domain/          # IncidentTable, IncidentDrawer, NodeTable, SitesMap…
└── pages/               # un fichier par écran
```

**`api/noc.js` est volontairement un seul fichier** et non quinze modules
de six lignes : c'est le document de référence qui doit rester aligné
avec `backend/app/routes/`. Éclaté, la dérive entre les deux côtés passe
inaperçue.

---

## 8. Développement

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, proxy /api et /ws vers :8000
npm run build
npm run lint
```

Le proxy de `vite.config.js` suppose un backend sur `localhost:8000`. En
production, c'est nginx qui relaie (`frontend/nginx.conf` pour le
conteneur, `nginx/nginx.conf` pour la passerelle TLS).

Variables d'environnement facultatives :

| Variable | Effet |
|---|---|
| `VITE_API_URL` | base de l'API (défaut `/api`) |
| `VITE_WS_URL` | URL du flux temps réel (défaut : déduite de l'origine) |

### Vérifier l'alignement avec le backend

Un écart entre `api/noc.js` et les routes réelles ne se voit qu'à
l'exécution. Pour le détecter avant :

```bash
# depuis la racine du projet — compare les 71 appels du frontend
# aux 76 routes déclarées par FastAPI
python - <<'EOF'
import re, io
src = io.open("frontend/src/api/noc.js", encoding="utf-8").read()
print(len(re.findall(r'\b(get|post|patch|del)\(', src)), "appels déclarés")
EOF
```

---

## 9. Points d'attention connus

**La carte peut être vide.** `dim_locality.latitude` n'est renseignée que
par `etl/scripts/discover_geography.py`. Tant qu'il n'a pas tourné, aucun
site n'a de coordonnées. La carte annonce alors explicitement le nombre de
sites non localisés plutôt que d'afficher un fond vide.

**Le classement par ministère peut être vide.** Même cause :
`dim_ministry` n'est peuplée que par ce script.

**Certaines métriques sont absentes selon les outils.** Les tuiles
affichent « non collectée » et non « 0 ». Les onglets de télémétrie d'un
équipement ne montrent que les séries réellement reçues sur 7 jours.

**Le taux de couverture vaudra ~100 %** tant qu'un inventaire théorique
complet (CMDB iTop) n'alimentera pas `dim_node` : le parc de référence et
le parc supervisé sont aujourd'hui le même ensemble. L'écran le signale.

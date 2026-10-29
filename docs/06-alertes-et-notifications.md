# 6. Alertes et notifications

## Ce qui déclenche une notification

| Déclencheur | Quand | Code |
|---|---|---|
| **Nouvelle alerte d'un outil** | Le collecteur voit une alerte absente du cycle précédent, et la publie sur Redis | `collector/state.py` → `backend/app/services/realtime_service.py` |

C'est le seul déclencheur : le NOC ne crée pas d'alerte lui-même, et les
tickets iTop (`itsm_ticket`) ne sont pas diffusés comme des alertes. Une
notification sortante ne part que si :

1. `NOTIFICATIONS_ENABLED=true` ;
2. la gravité fait partie de `NOTIFY_SEVERITIES` (par défaut : `critical,high`,
   soit *critique* et *majeur*). Les gravités `info` et `unknown` ne
   déclenchent jamais d'envoi ;
3. l'alerte n'a **pas déjà été notifiée**.

Deux cas où **rien ne part**, volontairement :

- **Au tout premier démarrage** (Redis neuf ou vidé), toutes les alertes
  seraient « nouvelles » : rien n'est diffusé, sinon l'équipe recevrait des
  centaines de messages pour des pannes anciennes. Ce cas est reconnu par un
  marqueur durable (`noc:live:alerts:seen_since`), pas par l'absence
  d'alertes : un réseau sans aucune alerte qui voit apparaître une panne la
  notifie bien.

Après un **redémarrage ou une coupure du collecteur, même longue**, les
alertes apparues pendant la coupure sont diffusées et notifiées au retour :
la mémoire des alertes déjà vues (`noc:live:alerts:seen`) n'expire plus.
Pour qu'un retour de coupure ne déclenche pas des dizaines de messages,
au-delà de `NOTIFY_BURST_MAX` (10) nouvelles alertes graves dans un même
cycle, **un seul message récapitulatif** part (courriel et SMS), listant
jusqu'à 50 alertes. Chacune est tout de même réservée dans
`ops_alert_notified` : aucune ne sera notifiée une seconde fois.
- **Une alerte qui dure** n'est notifiée qu'une fois : seule la nouveauté est
  un événement.

## Les canaux

| Canal | Pour qui | Configuration |
|---|---|---|
| **Écran (WebSocket)** | Tous les utilisateurs connectés | Toujours actif (`REALTIME_ENABLED`) |
| **Courriel** | Comptes abonnés + listes fixes | `SMTP_*`, voir ci-dessous |
| **SMS** (Twilio) | Numéros de `NOC_SMS_RECIPIENTS` | `TWILIO_*` |
| **Notification navigateur** (Web Push) | Utilisateurs qui l'ont activée dans *Mon compte* | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` — ⚠️ l'abonnement s'enregistre, mais **aucun envoi n'est déclenché sur alerte** aujourd'hui (chapitre 10) |

## Le courriel en détail

### Qui reçoit

Les destinataires sont **l'addition** de deux sources, relues à chaque envoi :

1. **Les comptes abonnés** : actifs, avec une adresse courriel et la case
   « Recevoir les alertes graves par courriel » cochée. Le Chef NOC gère cela
   dans *Utilisateurs* ; chacun peut s'abonner lui-même dans *Mon compte*.
2. **Les listes fixes** : `NOC_EMAIL_RECIPIENTS` dans `.env` (adresses
   d'astreinte, listes de diffusion), séparées par des virgules.

Une même adresse présente dans les deux ne reçoit qu'un exemplaire. Un compte
désactivé cesse immédiatement de recevoir.

### Configuration SMTP

| Variable | Rôle | Exemple |
|---|---|---|
| `SMTP_HOST` | Serveur de messagerie. **Vide = courriel désactivé.** | `smtp.anptic.bf` |
| `SMTP_PORT` | Port | `587` (STARTTLS), `465` (TLS implicite), `25` (relais interne) |
| `SMTP_USE_TLS` | STARTTLS après connexion | `true` pour 587 |
| `SMTP_USE_SSL` | TLS dès la connexion. Vide = déduit du port (465 → oui) | vide |
| `SMTP_VERIFY_SSL` | Vérifier le certificat du serveur. `false` seulement pour un relais interne auto-signé | `true` |
| `SMTP_USER`, `SMTP_PASSWORD` | Authentification, si le serveur l'exige | |
| `SMTP_FROM` | Adresse d'expédition | `noc@anptic.bf` |
| `DASHBOARD_URL` | Adresse du NOC, pour le lien « Ouvrir le NOC » dans le courriel | `https://noc.anptic.bf` |

Après toute modification : `docker compose up -d backend`.

### Contenu d'un courriel

- **Objet** : `[NOC] Alerte CRITIQUE — <équipement>`.
- **Corps** (texte et HTML) : équipement, site, gravité, outil source, message
  de la sonde, lien vers le NOC.
- Tout texte venant d'un outil source est **échappé** dans le HTML : un message
  de sonde contenant des chevrons ne peut ni casser la mise en page ni injecter
  de contenu.

### Tester

1. En local, démarrer le faux serveur : `docker compose --profile mail up -d mailpit`,
   avec `SMTP_HOST=mailpit`, `SMTP_PORT=1025`, `SMTP_USE_TLS=false`. Les
   courriels se lisent sur <http://localhost:8025>.
2. Écran *Utilisateurs* → panneau **Alertes par courriel** : il affiche l'état
   de la chaîne (serveur, sécurité, destinataires effectifs).
3. Bouton **Envoyer un test**. Il fonctionne même si `NOTIFICATIONS_ENABLED=false`,
   pour valider la configuration **avant** d'activer les envois. En cas
   d'échec, le message exact du serveur SMTP est affiché.

## Garanties

| Garantie | Mécanisme |
|---|---|
| **Pas de doublon**, même avec plusieurs backends | Avant d'envoyer, le backend insère la clé de l'alerte dans `ops_alert_notified`. La clé primaire fait office de verrou : un seul backend réussit l'insertion, les autres n'envoient rien. |
| **Un envoi échoué est retenté** | Il est rangé dans `ops_notification_retry` et retenté à 1, 5, 15, 30 puis 60 minutes, tant que l'alerte est active, dans la limite de `NOTIFY_RETRY_MAX_ATTEMPTS` tentatives (6) et de `NOTIFY_RETRY_MAX_AGE_MIN` minutes (360). Courriel : destinataires relus à chaque tentative. SMS : seuls les numéros en échec sont retentés. Plusieurs backends ne retentent jamais le même envoi (`FOR UPDATE SKIP LOCKED`). |
| **Traçabilité** | Chaque envoi (réussi ou non) est journalisé dans `ops_notification_log` : canal, destinataires, statut, erreur. |
| **Un envoi lent ne bloque rien** | Les envois se font dans un fil séparé ; l'affichage temps réel n'attend pas le serveur SMTP. |
| **Une panne de messagerie n'arrête pas le NOC** | Les erreurs d'envoi sont journalisées, jamais propagées. |

> Un envoi qui échoue encore après toutes ses tentatives, ou dont l'alerte
> est trop ancienne, est **abandonné** : statut `abandoned` dans
> `ops_notification_log`, compteur `notifications.abandoned_24h` de
> `/api/health`, et alerte « notification d'alerte abandonnée » dans Zabbix
> si le NOC y est supervisé (chapitre 9). Une alerte refermée dans son outil
> entre-temps n'est plus notifiée.

## Diagnostic : pourquoi je ne reçois rien

Dans l'ordre :

1. **Le panneau *Alertes par courriel*** indique-t-il « Opérationnel » ? Sinon,
   il dit ce qui manque (SMTP non configuré, envoi coupé, aucun destinataire).
2. **Le bouton *Envoyer un test*** fonctionne-t-il ? Sinon, lire le message
   d'erreur SMTP affiché.
3. **Y a-t-il de nouvelles alertes ?** Avec le dump NetXMS ou l'export du
   journal Centreon (données figées), aucune alerte n'est jamais nouvelle :
   aucun courriel automatique ne part.
4. **La gravité est-elle dans `NOTIFY_SEVERITIES` ?**
5. **L'alerte a-t-elle déjà été notifiée, ou est-elle en attente ?**
   `docker compose exec -T postgres psql -U noc -d noc -c "select * from ops_notification_log order by id desc limit 10"`
   et, pour les envois à retenter :
   `docker compose exec -T postgres psql -U noc -d noc -c "select alert_key, channel, status, attempts, next_attempt_at, last_error from ops_notification_retry order by id desc limit 10"`
6. **Les journaux du backend** : `docker compose logs backend | grep -i courriel`.

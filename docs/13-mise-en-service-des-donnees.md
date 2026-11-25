# Mise en service des données (dump NetXMS, journaux des outils)

À dérouler **dans l'ordre**, à la réception du dump NetXMS. Chaque étape dit
ce qu'elle fait, la commande à taper, et ce qu'on doit voir. Si une
vérification ne donne pas le résultat attendu, **s'arrêter là** : la suite
s'appuie dessus.

Les commandes sont écrites pour **Git Bash**, à la racine du projet. Quand la
syntaxe diffère, la version PowerShell est donnée juste en dessous.

| Base | Service | Port local | Rôle |
|---|---|---|---|
| NetXMS (dump de l'agence) | `netxms-db` | 127.0.0.1:5438 | source, lue par le collecteur |
| NOC | `postgres` | 127.0.0.1:5436 | comptes, journal historique, bilans |

> ⚠️ Ne jamais restaurer le dump NetXMS dans la base du NOC (`postgres`).

> ℹ️ Les commandes sur la base du NOC utilisent `-U postgres` : c'est la
> valeur de `POSTGRES_USER` dans `.env` sur ce poste. Si ton `.env` en porte
> une autre (`noc` par défaut dans `.env.example`), remplace-la.

---

## 1. Préparer

### 1.1 Déposer le dump

Copier le fichier reçu dans `database/` **en le renommant avec le mot `dump`
dans son nom**, par exemple `database/netxms_dump_20261201.sql`. Il est ensuite
passé en argument à l'étape 3.

Le nom compte : git n'ignore que les fichiers `database/*dump*.sql` (et
l'ancien `netxmsbd07082026.sql`). Le dump contient des données de production :
il ne doit jamais être commité. Avant tout commit, vérifier qu'il n'apparaît
pas dans `git status`.

### 1.2 Compléter `.env`

Vérifier ou ajouter ces lignes, sans toucher au reste :

```ini
# Base NetXMS locale (section 6 de .env.example)
NETXMS_DB_USER=netxms
NETXMS_DB_PASSWORD=netxms_db_pass
NETXMS_DB_NAME=netxms
NETXMS_DB_READER_PASSWORD=<un mot de passe solide>

# Le collecteur lit la base restaurée avec le compte de lecture seule
NETXMS_API_URL=postgresql://netxms-db:5432/netxms
NETXMS_API_USER=noc_reader
NETXMS_API_PASSWORD=<le même que NETXMS_DB_READER_PASSWORD>
```

Les sources maîtres des pannes restent **désactivées** pour l'instant. Elles
sont activées à l'étape 5, une fois la table vérifiée.

---

## 2. Sauvegarder la base du NOC

À faire avant toute modification : la mise à jour du schéma (étape 4) est
sans danger, mais une sauvegarde ne coûte rien.

```bash
docker compose up -d backup
docker compose exec backup sh /usr/local/bin/noc-backup.sh now
```

**Attendu** : « Sauvegarde réussie : noc_AAAAMMJJ_HHMMSS.dump », dans
`BACKUP_DIR`. Les mêmes commandes valent sous PowerShell.

---

## 3. Restaurer le dump NetXMS

### 3.1 Démarrer la base NetXMS

```bash
docker compose --profile netxms up -d netxms-db
docker compose --profile netxms ps netxms-db
```

**Attendu** : `netxms-db` à l'état `healthy`.

### 3.2 Contrôle préalable, sans rien modifier

```bash
./database/restore_netxms_dump.sh database/netxms_dump_AAAAMMJJ.sql --dry-run
```

**Attendu** : « dump : … Mo », la liste des rôles trouvés, le plan. Aucune
erreur.

### 3.3 Restaurer

```bash
./database/restore_netxms_dump.sh database/netxms_dump_AAAAMMJJ.sql --force
```

`--force` remplace l'ancienne restauration, s'il y en a une. Le script :

1. restaure le dump ;
2. **purge les secrets** (communautés SNMP, mots de passe, jetons) ;
3. crée le compte `noc_reader`, avec ses droits de lecture. Cela comprend le
   droit sur `downtime_log` si la table existe.

**Attendu** : le script se termine par un message de succès. Le script
s'arrête à la première erreur : s'il annonce un succès, tout le dump est
passé.

---

## 4. Vérifier le dump avant de s'en servir

### 4.1 Version du schéma et présence de `downtime_log`

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT var_name, var_value FROM metadata WHERE var_name LIKE 'SchemaVersion%';"

docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT column_name, data_type FROM information_schema.columns
   WHERE table_schema = 'public' AND table_name = 'downtime_log'
   ORDER BY ordinal_position;"
```

**Attendu** : quatre colonnes, `object_id`, `start_time`, `end_time`, et
l'étiquette. Elle s'appelle `downtime_tag` en NetXMS 5 (schéma 50.x, celui de
l'agence, constaté sur le dump du 07/08/2026) et `tag` ailleurs. Les deux sont
acceptées.

- **Colonnes différentes**, ou **aucune ligne** (table absente) : s'arrêter et
  me transmettre la sortie de cette commande. Le connecteur ne lira rien tant
  que ce n'est pas corrigé ; il le signalera, sans inventer de données.

### 4.2 Contenu de `downtime_log`

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT count(*) AS pannes,
          count(*) FILTER (WHERE end_time = 0 OR end_time IS NULL) AS en_cours,
          count(DISTINCT object_id) AS objets,
          count(DISTINCT downtime_tag) AS etiquettes
   FROM downtime_log;"

docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT downtime_tag, count(*) FROM downtime_log GROUP BY 1 ORDER BY 2 DESC;"

docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT * FROM downtime_log ORDER BY start_time DESC LIMIT 10;"
```

**À noter** pour l'agence :

- la liste des **étiquettes** (`tag`). Il faut leur demander lesquelles sont de
  vraies pannes, pour régler `NETXMS_DOWNTIME_TAGS` si besoin ;
- la **période couverte** : comparer la date de la panne la plus ancienne et
  celle de la plus récente.

### 4.3 Le compte de lecture voit bien la table

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms -c \
  "SELECT has_table_privilege('noc_reader', 'public.downtime_log', 'SELECT');"
```

**Attendu** : `t`. Si c'est `f`, rejouer les droits :

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms
  -v ON_ERROR_STOP=1 -v reader_password="nDybLaY0kuXByj6WEnpzyyvoUMrM"
  -f - < database/netxms_readonly_role.sql
```

### 4.4 Inspection complète, facultative

Script Python, à lancer depuis le poste. Il demande `pip install psycopg2-binary` :

```bash
python database/inspect_netxms_schema.py --tables downtime_log,nodes,object_properties
```

---

## 5. Mettre à jour le NOC et activer les sources maîtres

### 5.1 Arrêter ce qui écrit dans la base du NOC

```bash
docker compose stop collector backend
```

### 5.2 Mettre le schéma à jour

Cette étape crée `hist_downtime` et `hist_source_sync`. Elle est rejouable sans
risque.

```bash
docker compose exec -T postgres psql -U postgres -d noc -v ON_ERROR_STOP=1 \
  < backend/sql/schema.sql

# Seulement si la base est suivie par Alembic. Sinon, l'erreur « relation
# alembic_version does not exist » signifie qu'il n'y a rien à faire (cas de
# ce poste).
docker compose exec -T postgres psql -U postgres -d noc \
  -c "UPDATE alembic_version SET version_num = '0013_availability_weights'"
```

PowerShell, pour la première commande :

```powershell
Get-Content backend/sql/schema.sql -Raw | docker compose exec -T postgres psql -U postgres -d noc -v ON_ERROR_STOP=1
```

**Vérifier** :

```bash
docker compose exec -T postgres psql -U postgres -d noc -c "\dt hist_*"
```

**Attendu** : `hist_alert`, `hist_alert_event`, `hist_downtime`,
`hist_source_object`, `hist_source_sync`, `hist_state`, `hist_tool_health`.

### 5.3 Activer les sources dans `.env`

Activer **NetXMS d'abord, seul**. Les autres outils s'activent de la même
façon une fois leur accès disponible (voir l'étape 8).

```ini
NETXMS_DOWNTIME_ENABLED=true
# Pannes d'équipement seulement. Sur le dump de l'agence : Node_Down
# (152 765 lignes) ; Service_Down (7 lignes) concerne des services.
NETXMS_DOWNTIME_TAGS=Node_Down
```

En local, l'adresse de la base est reprise de `NETXMS_API_URL` (étape 1.2). En
production, si l'inventaire passe par l'API Web de NetXMS, renseigner
`NETXMS_DOWNTIME_DSN`, `NETXMS_DOWNTIME_USER` et `NETXMS_DOWNTIME_PASSWORD`
avec le compte de lecture seule de l'agence.

### 5.4 Reconstruire et relancer

```bash
docker compose build --pull backend collector frontend nginx
docker compose up -d
# frontend et nginx ne sont pas toujours recréés : les forcer.
docker compose up -d --force-recreate frontend nginx
docker compose ps
```

**Attendu** : tous les services `running` ou `healthy`.

---

## 6. Vérifier que le NOC lit bien les sources

### 6.1 Connexions aux outils

```bash
docker compose logs --tail=200 collector | grep -iE "netxms|downtime|pannes"
```

**Attendu** : une ligne « Pannes netxms (netxms_downtime_log) : N ligne(s)… ».

- « colonnes … introuvables » : la table ne correspond pas à ce qui est
  attendu, revenir à l'étape 4.1.
- « droits manquants » : revenir à l'étape 4.3.

### 6.2 Pannes recopiées dans le NOC

```bash
docker compose exec -T postgres psql -U postgres -d noc -c \
  "SELECT source, synced_at, rows_read FROM hist_source_sync;"

docker compose exec -T postgres psql -U postgres -d noc -c \
  "SELECT source, count(*) AS pannes, count(*) FILTER (WHERE ended_at IS NULL) AS en_cours,
          count(DISTINCT node_id) AS equipements
   FROM hist_downtime GROUP BY source;"
```

**Attendu** :

- le nombre de pannes est proche de celui de l'étape 4.2 sur la même période.
  La première lecture remonte `NETXMS_DOWNTIME_BACKFILL_DAYS` jours (400 par
  défaut) ;
- NetXMS ne garde que les pannes récentes. Sur le dump de l'agence, aucune
  panne ne s'est terminée avant octobre 2025 : les 152 765 lignes sont toutes
  relues.

Résultat obtenu le 22/11/2026 sur le dump du 07/08/2026 :
- 152 765 pannes sur 1 267 équipements, dont 376 en cours ;
- 1 317 équipements calculés sur le journal NetXMS, 34 sur les observations
  du NOC (Zabbix, Centreon, NSP).

### 6.3 Écran Interopérabilité

Ouvrir le NOC, menu **Interopérabilité**. Chaque outil doit être joignable et
dater sa dernière collecte réussie.

---

## 7. Recalculer les bilans journaliers

Les courbes de la vue Direction lisent les bilans journaliers (`kpi_daily`).
Ceux déjà enregistrés ont été calculés avec les anciennes règles : il faut les
refaire.

### 7.1 Date de début de l'historique

NetXMS sait depuis quand il supervise chaque équipement (date de création de
l'objet). Le NOC reconstitue donc la disponibilité des équipements NetXMS
depuis la source seule, **avant même de les avoir observés** : l'historique
commence à la plus ancienne panne de `downtime_log`, pas au premier jour du
journal du NOC.

```bash
docker compose exec -T postgres psql -U postgres -d noc -At \
  -c "SELECT least((SELECT min(started_at) FROM hist_downtime),
                   (SELECT min(started_at) FROM hist_state))::date;"
```

Le compte de lecture doit voir la date de création. Le droit est dans
`database/netxms_readonly_role.sql` ; sur une base déjà restaurée :

```bash
docker compose --profile netxms exec -T netxms-db psql -U netxms -d netxms \
  -c "GRANT SELECT (creation_time) ON public.object_properties TO noc_reader;"
```

Vérifier que la synchronisation a enregistré les fenêtres de supervision et
l'horizon de la source (jusqu'où elle sait) :

```bash
docker compose exec -T postgres psql -U postgres -d noc \
  -c "SELECT source, horizon_at FROM hist_source_sync;" \
  -c "SELECT count(*) FILTER (WHERE managed) AS geres, count(*) FILTER (WHERE NOT managed) AS non_geres FROM hist_source_object;"
```

### 7.2 Recalcul

Remplacer `AAAA-MM-JJ` par la date obtenue à l'étape 7.1, et la date de fin
par la veille :

```bash
docker compose exec collector python -m collector.history rebuild-daily \
  --from AAAA-MM-JJ --to AAAA-MM-JJ --overwrite
```

**Attendu** : une ligne par jour recalculé (« AAAA-MM-JJ : N ligne(s) »).

**Base figée (dump).** La source ne sait rien au-delà de son horizon (sur le
dump de l'agence : 7 août 2026 à 11 h 24). Entre l'horizon et la première
observation du NOC, le temps reste **non observé** : il ne compte ni pour ni
contre. Une fenêtre « 30 derniers jours » ne montre donc que ce que le NOC a
vu lui-même ; pour l'historique, choisir 90 jours ou 12 mois. Sur la base
vivante de production, l'horizon suit le présent et ce trou n'existe pas.

Les équipements non gérés dans NetXMS (statut « unmanaged » ou désactivé) ne
sont pas reconstitués : NetXMS ne les supervise pas.

**Rétention de NetXMS.** NetXMS efface les pannes terminées au-delà de
`DowntimeLog.RetentionTime` jours (90 sur le serveur de l'agence). Avant
cette limite, il ne reste que les pannes encore ouvertes, et reconstituer la
disponibilité reviendrait à l'inventer. Le NOC ne reconstitue donc rien avant
la plus ancienne panne terminée encore présente (`complete_since`). Sur le dump
du 07/08/2026, cela donne un historique fiable du **9 mai au 7 août 2026**.

En production, le NOC garde chaque panne qu'il a copiée : son historique
s'allonge à partir de la première synchronisation, au-delà des 90 jours de
NetXMS. Pour récupérer plus de passé, l'agence peut aussi augmenter
`DowntimeLog.RetentionTime` sur son serveur (par exemple 400 jours) : le
journal est peu volumineux.

Contrôle (étape 7.1) :

```bash
docker compose exec -T postgres psql -U postgres -d noc \
  -c "SELECT source, complete_since, horizon_at FROM hist_source_sync;"
```

Résultat obtenu le 22/11/2026 (dump du 07/08/2026), disponibilité moyenne des
bilans journaliers du parc : mai 73,9 % (à partir du 9), juin 70,9 %,
juillet 68,6 %, août 68,2 % (jusqu'au 7).

---

## 8. Activer les autres outils

Ces outils passent par **leurs API déjà configurées** : aucun accès
supplémentaire n'est demandé. Activer une source à la fois, puis refaire les
étapes 6.2 et 7.2.

```ini
# Centreon : changements d'état confirmés des hôtes (chronologie de l'API REST)
CENTREON_DOWNTIME_ENABLED=true
# Zabbix : événements des déclencheurs de disponibilité (Ping, agent)
ZABBIX_DOWNTIME_ENABLED=true
# Nagios : changements d'état confirmés des hôtes (archivejson.cgi ou Livestatus)
NAGIOS_DOWNTIME_ENABLED=true
```

Après chaque modification de `.env` :

```bash
docker compose up -d collector backend
docker compose logs --tail=200 collector | grep -iE "pannes|downtime"
```

**iTop** n'a rien à activer : ses compteurs SLA sont lus automatiquement. Pour
vérifier que l'instance les fournit :

```bash
docker compose logs --tail=500 collector backend | grep -iE "itop.*(sla|compteurs)"
```

- Le message « tickets … sans compteurs SLA » signifie que l'instance ne les
  fournit pas. Les SLA restent alors calculés par le NOC, et la page SLA
  l'indique.

---

## 9. Rapprochement avec les chiffres de l'agence

À faire avant de renvoyer l'Excel à l'agence (feuille « Rapprochement dispo »).

1. **Choisir** un mois complet couvert à la fois par le journal du NOC et par
   `downtime_log`.
2. **Relever dans le NOC**, page Performance puis « Les moins disponibles sur
   la durée » :
   - la disponibilité pondérée ;
   - le nombre de pannes ;
   - la mention « pannes datées par l'outil ».
3. **Sur une fiche équipement**, la ligne « Écart avec les observations du NOC »
   donne le temps de panne vu par l'outil seul, et celui vu par le NOC seul.
4. **Comparer** avec :
   - les attributs de disponibilité calculés par l'agence dans NetXMS
     (`perAvailability`) ;
   - le rapport de disponibilité de Centreon ;
   - le rapport SLA d'iTop pour le respect des délais.
5. **Reporter** les écarts dans la feuille, avec leur explication.

---

## En cas de problème

| Symptôme | Cause probable | Action |
|---|---|---|
| Le script de restauration s'arrête | Dump incomplet ou corrompu | Redemander le dump ; relancer l'étape 3.3 |
| « colonnes … introuvables » dans les journaux | `downtime_log` différente de l'attendu | Transmettre la sortie de l'étape 4.1 |
| Aucune ligne dans `hist_source_sync` | Source non activée, ou collecteur pas redémarré | Étapes 5.3 et 5.4 |
| Disponibilités identiques à avant | Synchronisation de plus de 6 h : le NOC revient à ses observations | Étape 6.1 |
| Revenir en arrière | — | Mettre `*_DOWNTIME_ENABLED=false`, relancer : les calculs reviennent aux observations du NOC |
| Restaurer la base du NOC | — | [Chapitre 9](09-exploitation.md#sauvegarder-et-restaurer). Une ancienne sauvegarde `.sql` : `docker compose exec -T postgres psql -U postgres -d noc < sauvegarde_noc_AAAA-MM-JJ.sql` |

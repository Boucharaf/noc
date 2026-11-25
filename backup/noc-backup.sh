#!/bin/sh
# Sauvegarde de la base du NOC — voir docs/09-exploitation.md.
#
#   noc-backup.sh run      boucle : une sauvegarde par jour (service `backup`)
#   noc-backup.sh now      une sauvegarde immédiate
#   noc-backup.sh verify   essai de restauration de la dernière sauvegarde
#   noc-backup.sh health   0 si la dernière sauvegarde réussie est récente
#
# Une sauvegarde n'est « réussie » que si elle a été RESTAURÉE, dans un
# PostgreSQL jetable à l'intérieur de ce conteneur (la base du NOC n'est
# jamais touchée), et copiée hors du serveur quand c'est configuré.
#
# Pas de `set -e` : il est sans effet dans une fonction appelée par `if`.
# Chaque étape qui peut échouer porte son `|| return 1`.
set -u
umask 077

DIR="${BACKUP_LOCAL:-/backups}"
OFFSITE="${BACKUP_OFFSITE:-/offsite}"
# Emplacement hors serveur déclaré ? Vide = non.
OFFSITE_ENABLED="${BACKUP_OFFSITE_DIR:-}"
MARKER=".noc-hors-serveur"
HOUR="${BACKUP_HOUR:-2}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"
MAX_AGE_H="${BACKUP_MAX_AGE_H:-30}"
RETRY_S=900
WORK="${BACKUP_WORK:-/tmp/noc-restore}"
SUCCESS="$DIR/.derniere-reussite"

log() { echo "$(date '+%F %T') $*"; }
fail() { log "ERREUR : $*" >&2; return 1; }

latest() { ls -1 "$DIR"/noc_*.dump 2>/dev/null | sort | tail -n 1; }

# PostgreSQL refuse de tourner en root.
as_postgres() {
    if [ "$(id -u)" != 0 ]; then "$@"
    elif command -v gosu >/dev/null; then gosu postgres "$@"
    else su-exec postgres "$@"
    fi
}

stop_scratch() {
    [ -f "$WORK/data/postmaster.pid" ] \
        && as_postgres pg_ctl -D "$WORK/data" -m immediate -w stop >/dev/null 2>&1
    rm -rf "$WORK"
}

# Restaure $1 dans un serveur jetable (socket local, aucun port ouvert) et
# vérifie qu'il contient au moins un compte et les tables du journal.
restore_test() {
    stop_scratch
    mkdir -p "$WORK" && cp "$1" "$WORK/essai.dump" || return 1
    [ "$(id -u)" != 0 ] || chown -R postgres "$WORK" || return 1
    as_postgres initdb -D "$WORK/data" -U postgres -A trust >"$WORK/initdb.log" 2>&1 \
        || { cat "$WORK/initdb.log" >&2; return 1; }
    printf "%s\n" "listen_addresses = ''" "port = 5432" "fsync = off" \
        "unix_socket_directories = '$WORK'" >> "$WORK/data/postgresql.conf" || return 1
    as_postgres pg_ctl -D "$WORK/data" -w -l "$WORK/pg.log" \
        start >/dev/null || { cat "$WORK/pg.log" >&2; return 1; }
    # env -i : aucun PGHOST ni PGPASSWORD hérité ne peut viser la vraie base.
    scratch="env -i PATH=$PATH PGHOST=$WORK PGUSER=postgres"
    as_postgres $scratch createdb essai || return 1
    as_postgres $scratch pg_restore --exit-on-error --no-owner --no-privileges \
        -d essai "$WORK/essai.dump" || return 1
    counts=$(as_postgres $scratch psql -X -At -v ON_ERROR_STOP=1 -d essai -c \
        "SELECT (SELECT count(*) FROM noc_user) || ' ' || (SELECT count(*) FROM kpi_daily)
             || ' ' || (SELECT count(*) FROM hist_state)
             || ' ' || (SELECT count(*) FROM hist_alert)
             || ' ' || (SELECT count(*) FROM ops_audit_log)") || return 1
    if [ "${counts%% *}" = 0 ]; then fail "aucun compte dans la sauvegarde"; return 1; fi
    log "Restauration essayée (comptes, bilans, états, alertes, audit) : $counts"
}

verify() {
    [ -n "$1" ] || { fail "aucune sauvegarde"; return 1; }
    restore_test "$1"
    code=$?
    stop_scratch
    return $code
}

# Le fichier témoin distingue le vrai partage d'un dossier vide laissé par un
# partage démonté : sans lui, la copie « hors serveur » resterait sur le
# serveur sans que personne ne le voie.
offsite_copy() {
    if [ -z "$OFFSITE_ENABLED" ]; then
        log "ATTENTION : BACKUP_OFFSITE_DIR vide, aucune copie hors du serveur"
        return 0
    fi
    [ -f "$OFFSITE/$MARKER" ] \
        || { fail "$MARKER absent de BACKUP_OFFSITE_DIR : partage non monté ?"; return 1; }
    name=$(basename "$1")
    cp "$1" "$OFFSITE/.$name.partiel" || return 1
    cmp -s "$1" "$OFFSITE/.$name.partiel" || { fail "copie hors serveur différente"; return 1; }
    mv "$OFFSITE/.$name.partiel" "$OFFSITE/$name" || return 1
    log "Copie hors serveur vérifiée : $name"
}

# Purge, seulement après une réussite : une panne prolongée des sauvegardes
# ne doit jamais effacer les dernières bonnes.
purge() {
    find "$1" -maxdepth 1 -type f -name 'noc_*.dump' -mtime "+$KEEP_DAYS" -exec rm -f {} \;
}

backup() {
    mkdir -p "$DIR" || return 1
    rm -f "$DIR"/.noc_*.partiel
    name="noc_$(date +%Y%m%d_%H%M%S).dump"
    partial="$DIR/.$name.partiel"
    pg_dump -Fc -f "$partial" || { rm -f "$partial"; fail "pg_dump a échoué"; return 1; }
    verify "$partial" || { rm -f "$partial"; fail "sauvegarde non restaurable"; return 1; }
    mv "$partial" "$DIR/$name" || return 1
    if ! offsite_copy "$DIR/$name"; then
        # Gardée en local sous un nom fixe : un nouvel essai toutes les 15 min
        # pendant une panne du partage ne doit pas remplir le disque.
        mv "$DIR/$name" "$DIR/noc_$(date +%Y%m%d)_local.dump"
        return 1
    fi
    date +%F > "$SUCCESS" || return 1
    purge "$DIR"
    [ -z "$OFFSITE_ENABLED" ] || purge "$OFFSITE"
    log "Sauvegarde réussie : $name"
}

health() {
    [ -f "$SUCCESS" ] || return 1
    age=$(( $(date +%s) - $(date -r "$SUCCESS" +%s) ))
    [ "$age" -lt $(( MAX_AGE_H * 3600 )) ]
}

# Due : jamais faite, ou pas encore faite aujourd'hui et heure passée.
due() {
    [ -f "$SUCCESS" ] || return 0
    [ "$(cat "$SUCCESS")" != "$(date +%F)" ] || return 1
    now=$(date +%H)
    [ "${now#0}" -ge "${HOUR#0}" ] || ! health
}

run() {
    trap 'stop_scratch; exit 0' TERM INT
    while :; do
        pause=300
        if due; then backup || pause=$RETRY_S; fi
        sleep "$pause" &
        wait $!
    done
}

case "${1:-run}" in
    run) run ;;
    now) backup ;;
    verify) verify "$(latest)" ;;
    health) health ;;
    *) echo "usage : $0 run|now|verify|health" >&2; exit 2 ;;
esac

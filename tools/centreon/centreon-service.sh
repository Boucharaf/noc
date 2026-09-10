#!/bin/bash
# Minimal service manager for the daemons a Centreon central normally runs
# under systemd (cbd, centengine, gorgoned, centreontrapd).
#
# It is installed twice: as `centreon-service`, used by the entrypoint, and as
# `/usr/bin/systemctl` (the real one is diverted away), because Centreon's own
# sudoers rules whitelist `sudo /usr/bin/systemctl restart centengine` — that
# is how "Export configuration → Restart" in the web UI reaches the daemons.
set -uo pipefail

PID_DIR=/run/centreon-docker
LOG_DIR=/var/log/centreon-docker
SERVICES="cbd centengine gorgoned centreontrapd"

usage() {
  echo "usage: $(basename "$0") {start|stop|restart|reload|status} <${SERVICES// /|}>" >&2
  exit 2
}

# Strips the ".service" suffix systemd accepts, so unit names work as-is.
normalize() { echo "${1%.service}"; }

runner_for() {
  case "$1" in
    cbd) echo "centreon-broker /usr/sbin/cbwd /etc/centreon-broker/watchdog.json" ;;
    centengine) echo "centreon-engine /usr/sbin/centengine /etc/centreon-engine/centengine.cfg" ;;
    gorgoned) echo "centreon-gorgone /usr/bin/perl /usr/bin/gorgoned --config=/etc/centreon-gorgone/config.yaml --logfile=/var/log/centreon-gorgone/gorgoned.log --severity=${GORGONE_SEVERITY:-info}" ;;
    centreontrapd) echo "centreon /usr/share/centreon/bin/centreontrapd --logfile=/var/log/centreon/centreontrapd.log --severity=error --config=/etc/centreon/centreontrapd.pm --config-extra=/etc/centreon/conf.pm" ;;
    *) return 1 ;;
  esac
}

pid_of() {
  local pidfile="$PID_DIR/$1.pid"
  [ -f "$pidfile" ] || return 1
  local pid
  pid=$(cat "$pidfile")
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || return 1
  echo "$pid"
}

do_start() {
  local name=$1 runner user cmd
  if pid_of "$name" >/dev/null; then
    echo "$name already running"
    return 0
  fi
  runner=$(runner_for "$name") || { echo "unknown service: $name" >&2; return 1; }
  user=${runner%% *}
  cmd=${runner#* }
  mkdir -p "$PID_DIR" "$LOG_DIR"
  # Detached from the caller (the web UI restarts services through sudo, and
  # the daemon must outlive that short-lived shell).
  setsid runuser -u "$user" -- $cmd >> "$LOG_DIR/$name.out" 2>&1 &
  echo $! > "$PID_DIR/$name.pid"
  echo "$name started (pid $(cat "$PID_DIR/$name.pid"))"
}

do_stop() {
  local name=$1 pid
  pid=$(pid_of "$name") || { echo "$name not running"; return 0; }
  kill "$pid" 2>/dev/null
  for _ in $(seq 1 30); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -9 "$pid" 2>/dev/null
  rm -f "$PID_DIR/$name.pid"
  echo "$name stopped"
}

do_status() {
  local name=$1 pid
  if pid=$(pid_of "$name"); then
    echo "$name running (pid $pid)"
    return 0
  fi
  echo "$name stopped"
  return 3
}

action=${1:-}
shift || true

case "$action" in
  start | stop | restart | reload | status) ;;
  # systemd verbs that have no meaning here but must not fail the caller.
  enable | disable | daemon-reload | is-enabled | mask | unmask) exit 0 ;;
  *) usage ;;
esac

[ $# -ge 1 ] || usage

rc=0
for unit in "$@"; do
  name=$(normalize "$unit")
  runner_for "$name" >/dev/null || { echo "unknown service: $name" >&2; rc=1; continue; }
  case "$action" in
    start) do_start "$name" || rc=1 ;;
    stop) do_stop "$name" || rc=1 ;;
    restart | reload) do_stop "$name"; do_start "$name" || rc=1 ;;
    status) do_status "$name" || rc=$? ;;
  esac
done
exit $rc

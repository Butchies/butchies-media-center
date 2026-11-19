#!/bin/sh
# WD My Cloud OS 5 stop hook: stop.sh <app dir>
# Stops only this app's own server process (verified via /proc), never Emby or others.
set -eu
APP="${1:?WD application directory missing}"
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
bmc_trap
bmc_log "Stopp angefordert: app=$APP"
PIDFILE="$BMC_DATA/bmc.pid"
[ -f "$PIDFILE" ] || exit 0
IFS= read -r pid < "$PIDFILE" || exit 1
case "$pid" in ''|*[!0-9]*) echo 'Invalid PID; refusing to stop' >&2; exit 1;; esac
[ -r "/proc/$pid/cmdline" ] || { rm -f "$PIDFILE"; exit 0; }
if ! tr '\000' '\n' < "/proc/$pid/cmdline" | grep -Fx -- "$APP/server.py" >/dev/null 2>&1; then
 echo 'PID belongs to another process; refusing to stop' >&2; exit 1
fi
kill "$pid"
i=0
while [ -d "/proc/$pid" ] && [ $i -lt 20 ]; do sleep 0.5 2>/dev/null || sleep 1; i=$((i+1)); done
if [ -d "/proc/$pid" ]; then kill -9 "$pid" 2>/dev/null || true; fi
rm -f "$PIDFILE"
bmc_log "stopped pid=$pid"

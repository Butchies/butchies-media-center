#!/bin/sh
# WD My Cloud OS 5 init hook (after install and on every boot).
# Links the dashboard page that forwards to the media center on port 8097.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
bmc_trap
APP="${1:-$HERE}"
bmc_log "Init: app=$APP"
[ -d "$APP/wdweb" ] || { bmc_log "kein wdweb-Ordner in $APP"; exit 0; }
BMC_STEP="Dashboard-Seite verlinken"
mkdir -p "$BMC_WEBPATH"
for f in "$APP"/wdweb/*; do
 ln -sf "$f" "$BMC_WEBPATH/"
done
bmc_log "OK: Dashboard-Seite verlinkt nach $BMC_WEBPATH"
exit 0

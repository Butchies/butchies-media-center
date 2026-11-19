#!/bin/sh
# Installs an update that updater.py downloaded from GitHub and verified:
#   self_update.sh <installed app dir> <verified new package dir>
# Runs in its own session because install.sh stops the server that started it.
# Same steps as an update through the WD dashboard (install.sh: stop, back up all databases, swap
# the program folder and keep the previous one; then init.sh and start.sh).
# If the new version does not start, the previous program folder and the databases are put back
# and the previous version is started again. Media files, Emby and other apps are never touched.
set -u
APP="${1:?installed app dir missing}"
NEW="${2:?new package dir missing}"
. "$NEW/wd_env.sh"
NAS_PROG=$(dirname "$APP")
STATUS="$BMC_DATA/update/status.json"
OLD_VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$APP/apkg.rc" 2>/dev/null | head -n 1)
VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$NEW/apkg.rc" 2>/dev/null | head -n 1)
case "$VERSION" in ''|*[!0-9.]*) echo 'invalid version in package' >&2; exit 1;; esac
case "$OLD_VERSION" in *[!0-9.]*) OLD_VERSION=unbekannt;; esac

status() {
 mkdir -p "$BMC_DATA/update"
 printf '{"state":"%s","version":"%s","previous":"%s","message":"%s","time":%s}\n' \
  "$1" "$VERSION" "${OLD_VERSION:-unbekannt}" "$2" "$(date +%s)" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
 bmc_log "GitHub-Update $OLD_VERSION -> $VERSION: $2"
}

# Give the server time to answer the browser before it is stopped.
sleep "${BMC_UPDATE_DELAY:-2}"
status installing "Installiere Version $VERSION ..."
started=$(date +%s)

if ! sh "$NEW/install.sh" "$NEW" "$NAS_PROG"; then
 # install.sh changes nothing if the backup or the copy fails; restart the previous version.
 sh "$APP/start.sh" "$APP" || true
 status failed "Installation von $VERSION fehlgeschlagen. Version $OLD_VERSION laeuft unveraendert weiter (Details: Status und Diagnose im WD-Dashboard)."
 exit 1
fi
sh "$APP/init.sh" "$APP" || true
if sh "$APP/start.sh" "$APP"; then
 status done "Version $VERSION installiert. Die vorherige Version $OLD_VERSION ist gesichert."
 exit 0
fi

# The new version does not start: put the previous program and databases back.
status rollback "Version $VERSION startet nicht, stelle $OLD_VERSION wieder her ..."
sh "$APP/stop.sh" "$APP" || true
BACKUP=$(ls -1dt "$NAS_PROG/.$APKG_NAME.backup."* 2>/dev/null | head -n 1)
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP/server.py" ]; then
 status failed "Version $VERSION startet nicht und es gibt keine Programmsicherung. Bitte $OLD_VERSION ueber das WD-Dashboard neu installieren."
 exit 1
fi
mv "$APP" "$NAS_PROG/.$APKG_NAME.failed.$$" && mv "$BACKUP" "$APP" || {
 status failed "Zurueckstellen fehlgeschlagen. Bitte $OLD_VERSION ueber das WD-Dashboard neu installieren."; exit 1; }
rm -rf "$NAS_PROG/.$APKG_NAME.failed.$$"
SNAP=$(ls -1d "$BMC_DATA/backups/update-"*"-from-$OLD_VERSION" 2>/dev/null | tail -n 1)
if [ -n "$SNAP" ] && [ -f "$SNAP/restore.sh" ] && [ "$(stat -c %Y "$SNAP" 2>/dev/null || echo 0)" -ge "$((started - 60))" ]; then
 BMC_APP="$APP" sh "$SNAP/restore.sh" || true
fi
sh "$APP/init.sh" "$APP" || true
sh "$APP/start.sh" "$APP" || true
status failed "Version $VERSION startete nicht. Version $OLD_VERSION wurde mit den Daten von vor dem Update wiederhergestellt."
exit 1

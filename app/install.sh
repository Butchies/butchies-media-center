#!/bin/sh
# WD My Cloud OS 5 install hook.
# WD calls: install.sh <unpacked package dir> <Nas_Prog dir>
# The app is installed into <Nas_Prog>/butchiesmediacenter. Nothing else in
# Nas_Prog (for example Emby) is touched. Account data lives outside the app dir.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
SRC="${1:?WD install source missing}"
NAS_PROG="${2:?WD install destination missing}"
bmc_trap
bmc_log "Installation: quelle=$SRC nas_prog=$NAS_PROG"
BMC_STEP="Zielordner pruefen"
[ -d "$NAS_PROG" ] && [ ! -L "$NAS_PROG" ] || { echo 'Invalid Nas_Prog directory' >&2; exit 1; }
DST="$NAS_PROG/$APKG_NAME"
SRC_REAL=$(cd "$SRC" && pwd -P)
DST_PARENT_REAL=$(cd "$NAS_PROG" && pwd -P)
if [ "$SRC_REAL" = "$DST_PARENT_REAL/$APKG_NAME" ]; then
 # WD already unpacked the package in place: nothing to copy.
 bmc_log "package already in place"
 exit 0
fi
# A running copy of this app (and only this app) is stopped before the update.
BMC_STEP="laufende Version stoppen"
if [ -f "$DST/stop.sh" ]; then
 BMC_DATA="$BMC_DATA" sh "$DST/stop.sh" "$DST" || { echo 'Could not stop running app; update aborted' >&2; exit 1; }
fi
BMC_STEP="Datenbanken sichern"
# Before every update: integrity-checked copies of ALL databases plus restore.sh for a return to
# the previous version (newer database formats cannot be read by older versions).
# If the backup fails, the update is aborted and the installed version stays untouched.
if [ -f "$BMC_DATA/accounts.sqlite" ] || [ -f "$BMC_DATA/library.sqlite" ]; then
 PY=$(bmc_python) || { echo 'python3 not found' >&2; exit 1; }
 OLD_VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$DST/apkg.rc" 2>/dev/null | head -n 1)
 NEW_VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$HERE/apkg.rc" 2>/dev/null | head -n 1)
 if ! out=$("$PY" "$HERE/db_maintenance.py" snapshot "$BMC_DATA" "${OLD_VERSION:-unbekannt}" "${NEW_VERSION:-unbekannt}" 900 2>&1); then
  bmc_log "FEHLER: Datenbanksicherung fehlgeschlagen, Update abgebrochen: $out"; echo 'Database backup failed; update aborted' >&2; exit 1
 fi
 bmc_log "Datenbanken gesichert: $out"
fi
BMC_STEP="Programmdateien kopieren"
if ! out=$(BMC_DATA="$BMC_DATA" sh "$HERE/install_app.sh" "$SRC" "$DST" 2>&1); then
 bmc_log "install_app: $out"; echo "$out" >&2; exit 1
fi
bmc_log "install_app: $out"
# Keep only the newest backup of the previous program version.
newest=$(ls -1dt "$NAS_PROG/.$APKG_NAME.backup."* 2>/dev/null | head -n 1 || true)
for old in "$NAS_PROG/.$APKG_NAME.backup."*; do
 [ -e "$old" ] || continue
 [ "$old" = "$newest" ] || rm -rf "$old"
done
bmc_log "OK: Installation abgeschlossen in $DST"

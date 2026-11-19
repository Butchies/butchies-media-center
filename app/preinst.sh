#!/bin/sh
# WD My Cloud OS 5 pre-install hook: preinst.sh <app dir>
# WD runs it from the NEW package before the old version is removed (order seen on the NAS:
# clean.sh old, preinst.sh new, remove.sh old, install.sh new). The old version is still complete
# here, so all databases are backed up now, with restore.sh for a return to the old version.
# install.sh backs up again only if this step did not run.
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
APP="${1:-}"
bmc_log "Vorbereitung (preinst): $*"
if [ -f "$BMC_DATA/accounts.sqlite" ] || [ -f "$BMC_DATA/library.sqlite" ]; then
 PY=$(bmc_python) || { bmc_log 'preinst: python3 nicht gefunden, Sicherung folgt in install.sh'; exit 0; }
 OLD_VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$APP/apkg.rc" 2>/dev/null | head -n 1)
 NEW_VERSION=$(sed -n 's/^Version:[[:space:]]*//p' "$HERE/apkg.rc" 2>/dev/null | head -n 1)
 if out=$("$PY" "$HERE/db_maintenance.py" snapshot "$BMC_DATA" "${OLD_VERSION:-unbekannt}" "${NEW_VERSION:-unbekannt}" 2>&1); then
  bmc_log "Datenbanken vor dem Update gesichert: $out"
 else
  bmc_log "FEHLER: Datenbanksicherung in preinst fehlgeschlagen: $out"
  exit 1
 fi
fi
exit 0

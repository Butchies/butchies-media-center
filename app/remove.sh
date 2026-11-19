#!/bin/sh
# WD My Cloud OS 5 uninstall hook.
# Removes the program directory and dashboard links. The account database in
# BMC_DATA and all media files are kept, so a reinstall keeps your login.
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
APP="${1:?WD application directory missing}"
bmc_log "Deinstallation: app=$APP (Kontodaten in $BMC_DATA bleiben erhalten)"
[ -f "$APP/stop.sh" ] && sh "$APP/stop.sh" "$APP" || true
case "$BMC_WEBPATH" in
 */butchiesmediacenter) rm -rf "$BMC_WEBPATH" ;;
esac
# Only ever delete a directory that is really this app.
case "$APP" in
 */butchiesmediacenter)
  if [ -d "$APP" ] && [ ! -L "$APP" ] && [ -f "$APP/server.py" ] && grep -q '^Package: butchiesmediacenter' "$APP/apkg.rc" 2>/dev/null; then
   rm -rf "$APP"
  else
   echo 'Refusing to delete: not a Butchies Media Center directory' >&2; exit 1
  fi ;;
 *) echo 'Refusing to delete unexpected path' >&2; exit 1 ;;
esac
exit 0

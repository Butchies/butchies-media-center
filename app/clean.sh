#!/bin/sh
# WD My Cloud OS 5 clean hook: removes only the dashboard links of this app.
# The status log stays for diagnosis. User data, media files and other apps (Emby)
# are never touched.
HERE=$(cd "$(dirname "$0")" && pwd)
. "$HERE/wd_env.sh"
bmc_log "Aufraeumen (clean): $*"
case "$BMC_WEBPATH" in
 */butchiesmediacenter)
  for f in "$BMC_WEBPATH"/*; do
   [ -L "$f" ] && rm -f "$f"
  done ;;
esac
exit 0

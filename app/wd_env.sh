#!/bin/sh
# Shared settings for the WD My Cloud OS 5 lifecycle scripts.
# Every path can be overridden through the environment (used by the test suite).
APKG_NAME=butchiesmediacenter
BMC_DATA="${BMC_DATA:-/mnt/HD/HD_a2/butchiesmediacenter-data}"
BMC_PORT="${BMC_PORT:-8097}"
BMC_MEDIA="${BMC_MEDIA:-/mnt/HD/HD_a2/Public}"
BMC_WEBPATH="${BMC_WEBPATH:-/var/www/butchiesmediacenter}"
BMC_LOG="${BMC_LOG:-/tmp/butchiesmediacenter.log}"
EMBY_PORT=8096
# The WD app manager runs hooks with a minimal PATH; add the usual places for
# python3/openssl on My Cloud OS 5 (system, /usr/local, Entware /opt).
PATH="${PATH:-/usr/bin:/bin}:/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/usr/local/sbin:/opt/bin:/opt/sbin:/opt/local/bin"
export PATH

# Status shown on the app page in the WD dashboard (status.txt next to index.html),
# so problems can be diagnosed without SSH. Also written to $BMC_LOG.
BMC_STATUS="$BMC_WEBPATH/status.txt"
bmc_log() {
 line="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null) [$(basename "$0")] $*"
 printf '%s\n' "$line" >> "$BMC_LOG" 2>/dev/null || true
 mkdir -p "$BMC_WEBPATH" 2>/dev/null || true
 if [ -f "$BMC_STATUS" ] && [ "$(wc -c < "$BMC_STATUS" 2>/dev/null || echo 0)" -gt 65536 ]; then
  tail -n 200 "$BMC_STATUS" > "$BMC_STATUS.tmp" 2>/dev/null && mv "$BMC_STATUS.tmp" "$BMC_STATUS" 2>/dev/null || true
 fi
 printf '%s\n' "$line" >> "$BMC_STATUS" 2>/dev/null || true
}

# Log the step a script stopped at, with its exit code (call once per script).
BMC_STEP=start
bmc_trap() {
 trap 'rc=$?; if [ "$rc" -ne 0 ]; then bmc_log "FEHLER: abgebrochen bei Schritt \"$BMC_STEP\" (Exit $rc)"; fi' EXIT
}

bmc_python() {
 if [ -n "${BMC_PYTHON:-}" ]; then echo "$BMC_PYTHON"; return 0; fi
 for p in /usr/bin/python3 /usr/local/bin/python3 /opt/bin/python3 /opt/local/bin/python3 \
          /usr/bin/python3.9 /usr/local/bin/python3.9 /opt/bin/python3.9; do
  if [ -x "$p" ]; then echo "$p"; return 0; fi
 done
 command -v python3 2>/dev/null || command -v python3.9 2>/dev/null
}

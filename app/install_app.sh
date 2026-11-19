#!/bin/sh
set -eu
# WD call convention still unverified; do not deploy without device verification.
SRC="${1:?WD install source missing}"
DST="${2:?WD install destination missing}"
DATA="${BMC_DATA:-/mnt/HD/HD_a2/butchiesmediacenter-data}"
[ -d "$SRC" ] && [ ! -L "$SRC" ] || { echo 'Invalid source' >&2; exit 1; }
[ -f "$SRC/server.py" ] && [ -f "$SRC/auth.py" ] || exit 1
# Refuse copying source into itself or its own descendants.
case "$DST/" in "$SRC/"*) echo "Destination is inside source" >&2; exit 1;; esac
case "$SRC/" in "$DST/"*) echo "Source is inside destination" >&2; exit 1;; esac
[ ! -L "$DST" ] || { echo 'Symlink destination refused' >&2; exit 1; }
[ ! -e "$DST" ] || [ -d "$DST" ] || exit 1
[ ! -L "$DATA" ] || { echo 'Symlink data path refused' >&2; exit 1; }
mkdir -p "$DATA"
chmod 700 "$DATA"
# Never let an installer place the application inside the private data directory.
case "$DST/" in "$DATA/"*) echo "Destination overlaps data directory" >&2; exit 1;; esac
case "$DATA/" in "$DST/"*) echo "Data directory overlaps destination" >&2; exit 1;; esac
# Refuse updates while a managed server is running; never stop unknown processes.
if [ -f "$DATA/bmc.pid" ]; then
 IFS= read -r pid < "$DATA/bmc.pid" || pid=''
 case "$pid" in ''|*[!0-9]*) echo 'Invalid PID; refusing update' >&2; exit 1;; esac
 if [ -d "/proc/$pid" ]; then echo 'Stop app before updating' >&2; exit 1; fi
fi
PARENT=$(dirname "$DST")
BASE=$(basename "$DST")
[ -d "$PARENT" ] && [ ! -L "$PARENT" ] || { echo 'Invalid destination parent' >&2; exit 1; }
STAGE="$PARENT/.$BASE.stage.$$"
BACKUP="$PARENT/.$BASE.backup.$$"
[ ! -e "$STAGE" ] && [ ! -e "$BACKUP" ] || exit 1
cleanup() { [ ! -e "$STAGE" ] || rm -rf "$STAGE"; }
trap cleanup EXIT HUP INT TERM
# Stage a complete copy before modifying the live installation.
mkdir "$STAGE"
cp -R "$SRC"/. "$STAGE"/
# Prevent source-controlled symlinks in the executable application tree.
if [ -n "$(find "$STAGE" -type l -print -quit)" ]; then
 echo "Application payload contains symlinks; refusing install" >&2
 exit 1
fi
[ -f "$STAGE/server.py" ] && [ -f "$STAGE/auth.py" ] || exit 1
if [ -d "$DST" ]; then
 mv "$DST" "$BACKUP"
 if mv "$STAGE" "$DST"; then
  echo "Update complete; previous version preserved: $BACKUP"
 else
  mv "$BACKUP" "$DST" || echo 'CRITICAL: restore backup manually' >&2
  exit 1
 fi
else
 mv "$STAGE" "$DST"
 echo 'First installation complete'
fi
trap - EXIT HUP INT TERM

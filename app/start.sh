#!/bin/sh
# WD My Cloud OS 5 start hook: start.sh <app dir>
# Starts the media center on port 8097 (HTTPS with a self-signed certificate).
# Port 8096 (Emby) is never used, and a port that is already taken is never seized.
set -eu
APP="${1:?WD application directory missing}"
. "$APP/wd_env.sh"
bmc_trap
DATA="$BMC_DATA"
PORT="$BMC_PORT"
bmc_log "Start angefordert: app=$APP daten=$DATA port=$PORT user=$(id -u 2>/dev/null) arch=$(uname -m 2>/dev/null)"

BMC_STEP="Python suchen"
PY=$(bmc_python) || PY=''
if [ -z "$PY" ]; then
 bmc_log "FEHLER: python3 nicht gefunden (PATH=$PATH)"; echo 'python3 not found' >&2; exit 1
fi
bmc_log "Python: $PY ($("$PY" --version 2>&1))"

BMC_STEP="Programmdateien pruefen"
[ -f "$APP/server.py" ] || exit 1
[ -f "$APP/auth.py" ] || exit 1
case "$PORT" in ''|*[!0-9]*) echo 'Invalid port' >&2; exit 1;; esac
if [ "$PORT" = "$EMBY_PORT" ]; then echo 'Port 8096 is reserved for Emby; refusing start' >&2; exit 1; fi

BMC_STEP="Datenordner"
[ ! -L "$DATA" ] || { echo "Symlink data path refused" >&2; exit 1; }
mkdir -p "$DATA"
[ -d "$DATA" ] && [ ! -L "$DATA" ] || exit 1
chmod 700 "$DATA"

BMC_STEP="RC20-Konto uebernehmen"
LEGACY_DB="${BMC_LEGACY_DB:-$BMC_MEDIA/ButchiesMediaCenter/test-data/accounts.sqlite}"
legacy=$("$PY" "$APP/db_maintenance.py" adopt-legacy "$DATA" "$LEGACY_DB" 2>&1) || legacy="fehlgeschlagen (ignoriert): $legacy"
bmc_log "Kontouebernahme: $legacy"

BMC_STEP="PID-Datei"
PIDFILE="$DATA/bmc.pid"
if [ -f "$PIDFILE" ]; then
 IFS= read -r pid < "$PIDFILE" || pid=''
 case "$pid" in ''|*[!0-9]*) echo 'Invalid PID file; refusing start' >&2; exit 1;; esac
 if [ -d "/proc/$pid" ]; then
  # Refuse duplicate start only if the PID belongs to our own application.
  if [ -r "/proc/$pid/cmdline" ] && tr '\000' '\n' < "/proc/$pid/cmdline" | grep -Fx -- "$APP/server.py" >/dev/null 2>&1; then
   bmc_log "Server laeuft bereits (pid $pid)"; echo 'Server already running' >&2; exit 0
  fi
  echo 'Stale PID refers to a different process; clearing PID file' >&2
 fi
 rm -f "$PIDFILE"
fi

BMC_STEP="Port $PORT pruefen"
# Never replace or interrupt a server that already owns this port. Right after an update the
# previous server may still be shutting down, so wait up to BMC_PORT_WAIT seconds (default 30).
port_free() {
"$PY" - "$PORT" <<'PYCODE'
import socket,sys
for host in ('127.0.0.1','0.0.0.0'):
 s=socket.socket()
 try:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
  s.bind((host,int(sys.argv[1])))
 except OSError:raise SystemExit(1)
 finally:s.close()
PYCODE
}
waited=0
PORT_WAIT="${BMC_PORT_WAIT:-30}"
until port_free; do
 if [ "$waited" -ge "$PORT_WAIT" ]; then
  holder=$(netstat -tlnp 2>/dev/null | grep ":$PORT " | head -n 3 | tr -s ' ' | tr '\n' ';')
  bmc_log "FEHLER: Port $PORT ist seit $waited s belegt (${holder:-Programm nicht ermittelbar}). Nichts wurde beendet."
  echo 'Port already in use' >&2; exit 1
 fi
 [ "$waited" -eq 0 ] && bmc_log "Port $PORT noch belegt, warte bis zu $PORT_WAIT s"
 sleep 2; waited=$((waited+2))
done

# HTTPS: self-signed certificate, created once and kept in the private data directory.
BMC_STEP="HTTPS-Zertifikat"
TLS_DIR="$DATA/tls"
CERT="$TLS_DIR/cert.pem"
KEY="$TLS_DIR/key.pem"
SCHEME=http
if [ "${BMC_DISABLE_TLS:-0}" != 1 ]; then
 if [ ! -s "$CERT" ] || [ ! -s "$KEY" ]; then
  mkdir -p "$TLS_DIR"; chmod 700 "$TLS_DIR"
  if command -v openssl >/dev/null 2>&1; then
   SUBJ="/CN=Butchies Media Center"
   if openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "$SUBJ" \
        -keyout "$KEY.tmp" -out "$CERT.tmp" >/dev/null 2>"$TLS_DIR/openssl.err"; then
    mv "$KEY.tmp" "$KEY"; mv "$CERT.tmp" "$CERT"
   else
    rm -f "$KEY.tmp" "$CERT.tmp"
    bmc_log "Zertifikat konnte nicht erzeugt werden: $(head -c 300 "$TLS_DIR/openssl.err" 2>/dev/null)"
   fi
  else
   bmc_log 'openssl nicht gefunden; HTTPS nicht moeglich'
  fi
  [ -f "$KEY" ] && chmod 600 "$KEY"
 fi
 if [ -s "$CERT" ] && [ -s "$KEY" ] && "$PY" -c 'import ssl' 2>/dev/null; then
  SCHEME=https
  export BMC_TLS_CERT="$CERT" BMC_TLS_KEY="$KEY"
 else
  bmc_log 'WARNUNG: Start ohne HTTPS (http:// im Heimnetz)'
 fi
fi

# LAN access: browsers may use the NAS IP (always allowed) or its host name.
BMC_STEP="Netzwerk"
HN=$(hostname 2>/dev/null | tr 'A-Z' 'a-z' || true)
HOSTS="${BMC_ALLOWED_HOSTS:-}"
if [ -n "$HN" ]; then
 HOSTS="$HOSTS${HOSTS:+,}$HN:$PORT,$HN.local:$PORT"
fi
export BMC_ALLOWED_HOSTS="$HOSTS"
export BMC_BIND="${BMC_BIND:-0.0.0.0}" BMC_PORT="$PORT" BMC_DATA="$DATA" BMC_MEDIA="$BMC_MEDIA"

# Tell the dashboard page which address to open.
if [ -d "$APP/wdweb" ]; then
 printf 'window.BMC={scheme:"%s",port:%s};\n' "$SCHEME" "$PORT" > "$APP/wdweb/config.js" 2>/dev/null || true
fi

BMC_STEP="Server starten"
"$PY" "$APP/server.py" >> "$DATA/server.log" 2>&1 &
pid=$!
printf '%s\n' "$pid" > "$PIDFILE"
sleep 3
if ! kill -0 "$pid" 2>/dev/null; then
 rm -f "$PIDFILE"
 bmc_log "FEHLER: Server nach dem Start beendet. Letzte Zeilen aus server.log:"
 tail -n 25 "$DATA/server.log" 2>/dev/null | while IFS= read -r l; do bmc_log "  | $l"; done
 echo 'Server failed to start (see server.log)' >&2; exit 1
fi
bmc_log "OK: Server laeuft (pid $pid) auf $SCHEME://<NAS-IP>:$PORT/"
tail -n 3 "$DATA/server.log" 2>/dev/null | while IFS= read -r l; do bmc_log "  | $l"; done

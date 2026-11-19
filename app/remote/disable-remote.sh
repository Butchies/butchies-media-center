#!/bin/sh
# Butchies Media Center – Streamen von unterwegs wieder ausschalten (Tür auf Port 8920 schließen).
P=${BMC_PROXY_DIR:-/mnt/HD/HD_a2/butchies-raucherstube/https-proxy}
CONF=$P/httpd-https.conf
INC=$P/media-8920.conf
HTTPD=${BMC_HTTPD:-/usr/local/apache2/bin/httpd}
[ -x "$HTTPD" ] || HTTPD=$(command -v httpd)
sed -i "\#^Include $INC#d" "$CONF"
rm -f "$INC"
"$HTTPD" -f "$CONF" -k graceful >/dev/null 2>&1 && echo "[Butchies] Zugriff von unterwegs ist aus." \
  || echo "[Butchies] Bitte 'sh $P/start-https.sh' ausführen."
echo "[Butchies] Die Portfreigabe im Router kannst du jetzt auch löschen."

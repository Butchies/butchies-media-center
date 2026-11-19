#!/bin/sh
# Butchies Media Center – Streamen von unterwegs einschalten.
# Legt im vorhandenen HTTPS-Proxy (Apache der Website butchies-groove.duckdns.org) eine zweite,
# verschlüsselte Tür auf Port 8920 an, die zum Media Center (Port 8097) weiterleitet.
# Das vorhandene Zertifikat der Website wird mitbenutzt. Die Website selbst bleibt unverändert.
set -u
P=${BMC_PROXY_DIR:-/mnt/HD/HD_a2/butchies-raucherstube/https-proxy}
CONF=$P/httpd-https.conf
INC=$P/media-8920.conf
HTTPD=${BMC_HTTPD:-/usr/local/apache2/bin/httpd}
PORT=${BMC_REMOTE_PORT:-8920}

say() { echo "[Butchies] $*"; }
[ -f "$CONF" ] || { say "FEHLER: $CONF nicht gefunden – ist der HTTPS-Proxy der Website eingerichtet?"; exit 1; }
[ -x "$HTTPD" ] || HTTPD=$(command -v httpd 2>/dev/null || echo "")
[ -n "$HTTPD" ] || { say "FEHLER: Apache (httpd) nicht gefunden."; exit 1; }

CERT=$(sed -n 's/^[[:space:]]*SSLCertificateFile[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/p' "$CONF" | head -n1)
KEY=$(sed -n 's/^[[:space:]]*SSLCertificateKeyFile[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/p' "$CONF" | head -n1)
NAME=$(sed -n 's/^ServerName[[:space:]]*\(.*\)/\1/p' "$CONF" | head -n1)
[ -n "$CERT" ] && [ -n "$KEY" ] || { say "FEHLER: Zertifikat in $CONF nicht gefunden."; exit 1; }

WS=""
MODDIR=$(dirname "$(sed -n 's/^LoadModule proxy_http_module[[:space:]]*\(.*\)/\1/p' "$CONF" | head -n1)")
if [ -f "$MODDIR/mod_proxy_wstunnel.so" ] && ! grep -q "proxy_wstunnel_module" "$CONF"; then
  WS="LoadModule proxy_wstunnel_module $MODDIR/mod_proxy_wstunnel.so"
fi

cp -f "$CONF" "$CONF.before-media" 2>/dev/null
cat > "$INC.new" <<EOF
# Butchies Media Center – Zugriff von unterwegs (angelegt von enable-remote.sh)
$WS
Listen $PORT
LogFormat "%h %t \"%m %U\" %>s %b %D" bmcmedia
<VirtualHost *:$PORT>
    ServerName $NAME
    SSLEngine on
    SSLCertificateFile "$CERT"
    SSLCertificateKeyFile "$KEY"
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
    ProxyRequests Off
    ProxyPreserveHost Off
    ProxyAddHeaders On
    RequestHeader set X-Forwarded-Proto "https"
    ProxyTimeout 900
    <IfModule proxy_wstunnel_module>
        ProxyPass /socket ws://127.0.0.1:8097/socket
    </IfModule>
    ProxyPass / http://127.0.0.1:8097/ flushpackets=on
    ProxyPassReverse / http://127.0.0.1:8097/
    Header always set Strict-Transport-Security "max-age=31536000"
    ErrorLog "$P/logs/media-error.log"
    CustomLog "$P/logs/media-access.log" bmcmedia
</VirtualHost>
EOF
mv -f "$INC.new" "$INC"
grep -q "^Include $INC" "$CONF" || echo "Include $INC" >> "$CONF"

if ! "$HTTPD" -t -f "$CONF" >/tmp/bmc-remote-test.txt 2>&1; then
  say "FEHLER in der Einstellung – alles wird zurückgesetzt:"
  cat /tmp/bmc-remote-test.txt
  cp -f "$CONF.before-media" "$CONF"; rm -f "$INC"
  exit 1
fi
if "$HTTPD" -f "$CONF" -k graceful >/dev/null 2>&1; then
  say "Fertig. Der Proxy wurde neu geladen."
else
  say "Proxy-Neustart fehlgeschlagen – bitte 'sh $P/start-https.sh' ausführen."
fi
sleep 2
if (netstat -tln 2>/dev/null || ss -tln 2>/dev/null) | grep -q ":$PORT "; then
  say "Port $PORT ist offen. Adresse für unterwegs: https://$NAME:$PORT"
  say "Jetzt im Router eine Portfreigabe für TCP $PORT auf das NAS einrichten."
else
  say "Hinweis: Port $PORT ist noch nicht offen. Bitte 'sh $P/start-https.sh' ausführen und erneut prüfen."
fi

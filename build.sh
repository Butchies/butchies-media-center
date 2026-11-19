#!/bin/sh
# Baut das WD-App-Paket (MyCloudEX2Ultra) mit mksapkg-OS5 aus github.com/WDCommunity/wdpksrc.
# Aufruf: sh build.sh   ->  dist/butchiesmediacenter_<Version>_EX2Ultra.bin
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
T=${TMPDIR:-/tmp}/wdpksrc
[ -x "$T/mksapkg-OS5" ] || { rm -rf "$T"; git clone -q --depth 1 https://github.com/WDCommunity/wdpksrc.git "$T"; chmod +x "$T/mksapkg-OS5"; }
# mksapkg signiert per openssl BF-CBC -> unter OpenSSL 3 den "legacy"-Provider einschalten
C=$(mktemp); printf 'openssl_conf=i\n[i]\nproviders=p\n[p]\ndefault=d\nlegacy=l\n[d]\nactivate=1\n[l]\nactivate=1\n' > "$C"; export OPENSSL_CONF="$C"
APPDIR=$(cd "${1:-$HERE/app}" && pwd)
W=$(mktemp -d); cp -rL "$APPDIR" "$W/butchiesmediacenter"; rm -f "$W/butchiesmediacenter/apkg.sign"; find "$W" -name __pycache__ -prune -exec rm -rf {} +
# Jellyfin-Weboberfläche (GPL, unverändert) für das Python-Media-Center: aus dem neuesten Release von
# github.com/Butchies/jellyfin (enthält jellyfin-web), ohne .map-Dateien. Nicht im Git, nur im Paket.
if [ -f "$APPDIR/jf_api.py" ] && [ ! -f "$W/butchiesmediacenter/jfweb/index.html" ]; then
  WEB=${JFWEB_DIR:-${TMPDIR:-/tmp}/jfweb-cache/jellyfin/jellyfin-web}
  if [ ! -f "$WEB/index.html" ]; then
    mkdir -p "${TMPDIR:-/tmp}/jfweb-cache" && cd "${TMPDIR:-/tmp}/jfweb-cache"
    URL=$(curl -fsSL https://api.github.com/repos/Butchies/jellyfin/releases/latest | grep -o '"browser_download_url": *"[^"]*armhf\.tar\.xz"' | head -n1 | sed 's/.*"\(https[^"]*\)"/\1/')
    curl -fsSL -o jf.tar.xz "$URL" && tar -xJf jf.tar.xz jellyfin/jellyfin-web && rm -f jf.tar.xz
    cd - >/dev/null
  fi
  mkdir -p "$W/butchiesmediacenter/jfweb"
  (cd "$WEB" && tar -cf - --exclude='*.map' .) | (cd "$W/butchiesmediacenter/jfweb" && tar -xf -)
fi
# Eigenes FFmpeg/FFprobe (statisch, 64K-ausgerichtet für den 32-KB-Seiten-Kernel der WD EX2 Ultra) nach bin/
if [ -f "$APPDIR/jf_api.py" ]; then
  FFT=${FF_TARBALL:-${TMPDIR:-/tmp}/ffmpeg-armhf-static-64k.tar.xz}
  if [ ! -s "$FFT" ]; then
    URL=$(curl -fsSL "https://api.github.com/repos/Butchies/jellyfin/releases?per_page=30" | grep -o '"browser_download_url": *"[^"]*ffmpeg-[^"]*armhf-static-64k\.tar\.xz"' | head -n1 | sed 's/.*"\(https[^"]*\)"/\1/')
    curl -fsSL -o "$FFT" "$URL"
  fi
  mkdir -p "$W/butchiesmediacenter/bin" && tar -xJf "$FFT" -C "$W/butchiesmediacenter/bin" ./ffmpeg ./ffprobe ./COPYING.LGPLv2.1 2>/dev/null || tar -xJf "$FFT" -C "$W/butchiesmediacenter/bin"
  chmod +x "$W/butchiesmediacenter/bin/ffmpeg" "$W/butchiesmediacenter/bin/ffprobe"
fi
# Decoder-Kern des Butchies-Web-Players (FFmpeg als WebAssembly) nach bmcweb/player/core/
if [ -f "$APPDIR/bmcweb/player/player.js" ]; then
  WPT=${WP_TARBALL:-${TMPDIR:-/tmp}/bmc-webplayer-core.tar.xz}
  if [ ! -s "$WPT" ]; then
    URL=$(curl -fsSL "https://api.github.com/repos/Butchies/jellyfin/releases?per_page=30" | grep -o '"browser_download_url": *"[^"]*bmc-webplayer-core\.tar\.xz"' | head -n1 | sed 's/.*"\(https[^"]*\)"/\1/')
    curl -fsSL -o "$WPT" "$URL"
  fi
  mkdir -p "$W/butchiesmediacenter/bmcweb/player/core" && tar -xJf "$WPT" -C "$W/butchiesmediacenter/bmcweb/player/core"
fi
chmod +x "$W"/butchiesmediacenter/*.sh
VER=$(sed -n 's/^Version:[[:space:]]*//p' "$APPDIR/apkg.rc")
(cd "$W/butchiesmediacenter" && "$T/mksapkg-OS5" -E -s -m MyCloudEX2Ultra >/dev/null)
mkdir -p "$HERE/dist"; mv "$W"/MyCloudEX2Ultra_butchiesmediacenter_* "$HERE/dist/butchiesmediacenter_${VER}_EX2Ultra.bin"
rm -rf "$W" "$C"; echo "$HERE/dist/butchiesmediacenter_${VER}_EX2Ultra.bin"

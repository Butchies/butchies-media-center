# Butchies Media Center

Eigenes Media Center für die **WD My Cloud EX2 Ultra** (Filme, Serien, Musik).
Der Server ist in Python geschrieben (nur Standardbibliothek, Python 3.9 auf dem NAS) und spricht dieselbe Sprache wie Jellyfin.
Deshalb laufen die originale **Jellyfin-Weboberfläche** und die **Jellyfin-Apps** (Handy, Fire TV, Windows) damit.
Der echte Jellyfin-Server läuft auf diesem NAS nicht: Er braucht .NET, und .NET läuft auf dem 32-KB-Seiten-Kernel der WD nicht.

- Adresse zu Hause: `http://<NAS-IP>:8097`
- Unterwegs (optional, siehe `app/remote/`): `https://<deine-Adresse>:8920`

## Neue Version bekommen

1. Rechts auf **Releases** klicken.
2. Bei der neuesten Version die Datei `butchiesmediacenter_<Version>_EX2Ultra.bin` herunterladen.
3. WD-Dashboard → **Apps** → **„Manuell installieren“** → Datei auswählen.

Das NAS holt sich **nichts automatisch**. Es wird nur installiert, was du selbst installierst.

## Etwas ändern

1. Datei im Ordner `app/` anklicken → **Stift-Symbol** (Bearbeiten) → ändern → **„Commit changes“**.
2. GitHub baut dann automatisch eine neue `.bin`. Den Fortschritt siehst du unter **Actions**, das Ergebnis unter **Releases**.
3. Bei größeren Änderungen vorher die Versionsnummer erhöhen, in `app/apkg.rc` (`Version:`), `app/apkg.xml` (`<version>`) und `app/server.py` (`VERSION=`).

Selbst bauen auf einem Linux-Rechner: `sh build.sh` → Ergebnis in `dist/`.

## Was steckt in der .bin?

### Eigene Dateien (alle hier im Ordner `app/`)

| Datei | Aufgabe |
|---|---|
| `server.py` | Hauptprogramm: Webserver auf Port 8097, Medien-Scan, Bibliotheken, Anmeldung, Dateien ausliefern |
| `jf_api.py` | Jellyfin-Schnittstelle: Filme/Serien/Musik, Bilder, Abspielen (Direkt-Stream), Weiterschauen, Plugins, Branding |
| `jf_admin.py` | Dashboard-Verwaltung: Benutzer, Bibliotheken, Ordnerauswahl, Scan-Aufgabe |
| `jf_meta.py` | Metadaten: Plakate, Hintergründe, Logos, Beschreibung, Schauspieler (lokale NFO-Dateien, optional TMDb mit eigenem Schlüssel), Identifizieren |
| `jf_subs.py` | Untertitel: Dateien neben dem Film (.srt/.ass/.vtt) und eingebettete Spuren |
| `jf_images.py` | Bildverwaltung: Bilder hochladen, löschen, Reihenfolge ändern, anderes Bild von TMDb wählen (eigene Bilder in `data/meta/user/`, Dateien im Medienordner bleiben unverändert) |
| `jf_playlists.py` | Wiedergabelisten und Sammlungen |
| `jf_ws.py` | Live-Verbindung (WebSocket), damit „Gesehen“/Favoriten auf allen Geräten sofort stimmen |
| `auth.py` | Benutzerkonten und Passwörter (verschlüsselt mit scrypt) |
| `videoinfo.py` | Liest Auflösung, Laufzeit und Spuren direkt aus der Videodatei |
| `updater.py`, `self_update.sh` | Update aus den GitHub-Releases, nur auf Wunsch des Admins (alte Funktion, in der Jellyfin-Oberfläche derzeit nicht erreichbar) |
| `db_maintenance.py`, `migrate_accounts.py`, `migration_check.py` | Datenbank-Sicherung und Übernahme alter Daten |
| `setup_admin.py`, `qr_local.py`, `nas_preflight.py`, `run_local.py` | Hilfsprogramme: erstes Admin-Konto, QR-Code, Vorab-Prüfung, lokaler Test |
| `apkg.rc`, `apkg.xml` | Beschreibung der WD-App (Name, Version, Startreihenfolge) |
| `install.sh`, `preinst.sh`, `init.sh`, `start.sh`, `stop.sh`, `remove.sh`, `clean.sh`, `wd_env.sh`, `install_app.sh` | Schritte, die das WD-Dashboard beim Installieren, Starten, Stoppen und Entfernen ausführt |
| `wdweb/` | Kachel und Seite der App im WD-Dashboard |
| `bmcweb/bmc-detail.css`, `bmcweb/bmc-detail.js` | Detailseite von Filmen/Serien im gewohnten Aufbau (Poster links, Infos rechts, ganzseitiger Hintergrund) |
| `bmcweb/bmc-cardsize.css`, `bmcweb/bmc-cardsize.js` | Einstellung „Bildgröße“ (Einstellungen → Anzeige): Kachelgröße pro Gerät |
| `bmcweb/bmc-artwork.css`, `bmcweb/bmc-artwork.js` | Startseite: Kachelform passend zum Bildformat (hochkant, breit, quadratisch, 4:3, Banner) |
| `bmcweb/themes/*.css` | 6 Butchies-Designs (Einstellungen → Anzeige → Design): Aurora, Kinosaal Rot, Mitternachtsblau, OLED Schwarz, Smaragd, Sonnenuntergang |
| `bmcweb/bmc-core.js` | Kleine technische Hilfen in der Jellyfin-Oberfläche (Untertitel-Darstellung, Hinweise bei x265) |
| `bmcweb/bmc-player.css`, `bmcweb/bmc-player.js` | Aussehen des Players (Aufbau wie gewohnt: Logo, Titelzeilen, Reiter Info/Kapitel/Besetzung/Als Nächstes) |
| `bmcweb/player/` | Butchies-Web-Player für Browser, die einen Film nicht selbst können (nur mit Plugin „Browser-Hilfe“) |
| `bmcweb/tmdb-config.html`, `bmcweb/switch-config.html` | Einstellungsseiten der Plugins „TMDb-Metadaten“ und „Browser-Hilfe“ |
| `remote/enable-remote.sh`, `remote/disable-remote.sh` | Zugang von unterwegs über Port 8920 ein- bzw. ausschalten |
| `../design/` | Vorlagen-Pakete (Designsystem, Film-Detailseite) als Nachschlagewerk, nicht in der App |
| `../preview/index.html` | Designvorschau mit Beispieldaten (nicht in der App) |
| `cacert.pem` | Liste vertrauenswürdiger Zertifikate (für TMDb, falls dem NAS-Python welche fehlen) |

### Fremde Teile (werden beim Bauen dazugeladen, nicht verändert)

| Im Paket | Was | Lizenz | Woher |
|---|---|---|---|
| `jfweb/` | Jellyfin-Weboberfläche 10.11.11 | GPL-2.0 | Release `armhf-…` in [Butchies/jellyfin](https://github.com/Butchies/jellyfin/releases) (Quelle: jellyfin/jellyfin-web) |
| `bin/ffmpeg`, `bin/ffprobe` | FFmpeg 7.1.1, statisch für die WD gebaut | LGPL-2.1 | Release `ffmpeg-armhf-…` in Butchies/jellyfin (Bauanleitung: Workflow `ffmpeg-armhf.yml`) |
| `bmcweb/player/core/` | FFmpeg als WebAssembly für den Web-Player | LGPL-2.1 | Release `webplayer-core-…` in Butchies/jellyfin (Quelle: Ordner `webplayer/`) |

`build.sh` lädt diese Teile automatisch und packt alles mit `mksapkg-OS5` (aus [WDCommunity/wdpksrc](https://github.com/WDCommunity/wdpksrc)) zur `.bin`.

## Daten auf dem NAS

- Programm: `/mnt/HD/HD_a2/Nas_Prog/butchiesmediacenter`
- Deine Daten (Konten, Bibliotheken, Fortschritt, Bilder): `/mnt/HD/HD_a2/butchiesmediacenter-data`. Sie bleiben bei Updates erhalten.
- Medien: nur die Ordner, die **du** im Dashboard unter **Bibliotheken** auswählst. Deine Dateien werden nie verändert.

Änderungen der einzelnen Versionen stehen in [CHANGELOG.md](CHANGELOG.md).

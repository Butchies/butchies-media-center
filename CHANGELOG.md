# Änderungen – Butchies Media Center

Neueste zuerst.

## 19.11.2026 – Butchies Media Center 3.11.0: Player komplett
- **Schlaftimer** im Player (Mond-Symbol neben dem Tempo): 15/30/45/60/90/120 Minuten oder „Ende dieses Titels“ – danach hält die Wiedergabe an.
- **Warteschlange** als Reiter unter dem Player, wenn mehrere Titel nacheinander laufen (Wiedergabeliste, Sammlung, „Alle abspielen“).
- **Kapitel** aus der Datei: Markierungen auf der Zeitleiste, Kapitelname beim Ziehen, Knöpfe „Vorheriges/Nächstes Kapitel“, Reiter „Kapitel“.
- **Ton und Untertitel nach deinen Einstellungen** (Einstellungen → Wiedergabe / Untertitel): bevorzugte Tonsprache, „Standard-Tonspur abspielen“, Untertitel-Modus Standard / Immer / Nur erzwungene / Intelligent / Keine, bevorzugte Untertitelsprache.
- **Aktive Geräte** im Dashboard: wer gerade was schaut (Titel, Position, Pause, Gerät, App). **Geräte**-Seite mit allen Geräten, die sich angemeldet haben (umbenennen, entfernen). Jede Wiedergabe wird im Verlauf gespeichert (nur auf dem NAS).
- Gesperrte Filme (über 1080p bzw. Auflösung noch unbekannt): verständlicher deutscher Hinweis statt nur „nicht erlaubt“.
- Eingebettete Untertitel mit Standard-Markierung werden als solche erkannt.

## 19.11.2026 – Butchies Media Center 3.10.0: Medieninformationen komplett
- **Bilder bearbeiten** (⋮ → „Bilder bearbeiten“): Plakat, Hintergründe (mehrere, Reihenfolge mit ‹ ›), Logo, Vorschaubild, Banner hochladen, löschen oder über 🔍 ein anderes Bild von TMDb wählen. Bilder neben deinen Filmen werden dabei nie gelöscht oder verändert – „Löschen“ blendet sie nur aus. „Metadaten aktualisieren“ mit „Alle Bilder ersetzen“ stellt den Ursprung wieder her.
- **Feldsperren** (Metadaten bearbeiten → „Aktivierte Felder“ bzw. „Dieses Objekt sperren“): gesperrte Felder bleiben, wie sie sind, auch wenn TMDb später etwas anderes liefert. Gespeichert werden nur noch Felder, die du wirklich geändert oder gesperrt hast – alles andere aktualisiert sich weiter automatisch.
- **Herunterladen** (⋮ → „Herunterladen“): Admins immer, andere Benutzer nur mit Haken „Herunterladen von Inhalten erlauben“ (Dashboard → Benutzer → Benutzer anklicken).
- **Technikdaten** über das mitgelieferte ffprobe: HDR10/HDR10+/HLG/Dolby Vision, Bildrate, Bit-Tiefe, Kanäle (5.1/7.1), Tonformat (Dolby Digital, DTS-HD MA, TrueHD …), Sprache, erzwungene und Hörgeschädigten-Untertitel, Gesamt-Bitrate und **Kapitel** aus der Datei (im Player unter „Kapitel“). Alle Dateien werden nach dem Update einmal im Hintergrund neu eingelesen.
- Metadaten: Schlagwörter, Produktionsländer, Sortiertitel und Serienstatus (aus NFO, TMDb oder selbst eingetragen); TheTVDB-ID bei Serien.
- „Ähnlich wie dieses“ zeigt jetzt wirklich Ähnliches (gleiche Genres, Schauspieler, Studios, Schlagwörter, Jahrzehnt) statt Zufall.
- 6 **Butchies-Designs** unter Einstellungen → Anzeige → Design: Aurora, Kinosaal Rot, Mitternachtsblau, OLED Schwarz, Smaragd, Sonnenuntergang.

## 19.11.2026 – Butchies Media Center 3.9.8: Detailseite im gewohnten Aufbau
- Film-/Serien-Detailseite wie gewohnt (eigene Umsetzung nach Bildvorlage): Hintergrundbild über die ganze Seite, Poster links, rechts Logo bzw. Titel, Infozeile „★ 6,1 · Jahr · 1h, 38 Min. · [FSK] · Genres · Endet um“, Video/Audio/Untertitel in einer Zeile, Knöpfe als Pillen („Abspielen“, „Trailer“, „Zufällig“) und Kreise (Gesehen, Herz, ⋮), Beschreibung mit „Mehr“, „Regisseur: …“, darunter „Besetzung & Mitwirkende“ und „Ähnlich wie dieses“ über die volle Breite. Handy: untereinander.

## 19.11.2026 – Butchies Media Center 3.9.7: Bildgröße
- Neue Einstellung **Bildgröße** unter Einstellungen → Anzeige (unter „Anzeigemodus“): Extra klein, Kleiner, Klein, Standard, Groß, Größer, Extra groß. Wird sofort und nur für dieses Gerät gespeichert. Ein Wechsel des Anzeigemodus setzt sie auf Standard zurück.
- Berechnung: Kachelbreite = Fläche / max(Grundzahl + Anpassung, Mindestanzahl); Mindestanzahl Poster 3, Quadrat 2, Querformat/Banner 1. „Standard“ entspricht genau der bisherigen Größe.
- Startseite: Bildformate werden an die Oberfläche gemeldet (Bilder füllen die Kacheln), Kachelformen nach Bildformat (`bmc-artwork`), Designvorschau `preview/index.html`.

## 19.11.2026 – Butchies Media Center 3.9.6: eigenes GitHub-Projekt
- Alle Dateien der App liegen jetzt einzeln in diesem Projekt; GitHub baut die .bin automatisch (Releases).
- Keine automatische Bibliothek „Mediathek“ über den ganzen Public-Ordner mehr (stammte aus der alten App 1.0.35). Welche Ordner freigegeben werden, bestimmt nur der Nutzer selbst (Dashboard → Bibliotheken).

## 18.11.2026 – Butchies Media Center 3.9.5: Player wie Emby, Bibliotheken in Unterordnern
- Player noch näher am gewohnten Emby-Aufbau: ‹-Pfeil, weiße Zeitleiste, Seitenabstand, Symbole Klangwelle (Ton) und Tempo, 10-s-Spulen in beide Richtungen, Reiter „Info“, „Kapitel“, „Besetzung & Mitwirkende“, „Als Nächstes“ unter dem Player, Menü für die Wiedergabegeschwindigkeit.
- Bibliotheken: ein Unterordner (z. B. Public/Serien) darf jetzt eine eigene Bibliothek sein, auch wenn eine andere Bibliothek schon den ganzen Ordner umfasst – die genauere gewinnt (wie bei Jellyfin). Vorher kam „Fehler beim Hinzufügen eines Medienverzeichnisses“.

## 18.11.2026 – Butchies Media Center 3.9.4: neuer Standard-Player-Aufbau
- Player-Aufbau wie gewohnt aus Emby (eigene Umsetzung, Standard für alle, kein Plugin mehr): oben Zurück + Logo links, Lautstärke/Cast/Bild-in-Bild rechts; unten kleine Zeile (Jahr bzw. „S7:E3 - Folgenname“) + großer Titel, rechts Untertitel/Ton/Herz/Einstellungen/Vollbild; Zeitleiste über die ganze Breite, darunter „-Rest / Ende-Uhrzeit“; ganz unten links Vorherige/Zurück/Abspielen/Vor/Nächste.
- Plugins „Browser-Hilfe“ und „Butchies-Player-Aussehen“: ein/aus jetzt über „Einstellungen“ (der Jellyfin-Schalter zeigte nach dem Einschalten fälschlich „aus“); Warnung „Fehler beim Abrufen aus dem Software-Depot“ behoben.
- „Identifizieren“: zusätzlich Suche über die TheTVDB-ID; der Pfad wird wie in Emby ab dem Medienordner angezeigt (z. B. Public/FULL HD CINEMA/x265/Film.mkv).

## 18.11.2026 – Butchies Media Center 3.9.3: reiner Direkt-Stream
- Das NAS gibt jeden Film nur noch unverändert weiter (Direkt-Stream). Kein Umpacken, kein Umrechnen, kein Ersatz-Player.
- Abgespielt wird nur auf dem Gerät (Windows-Programm, Fire TV, Handy, Moonfin, Browser). Kann ein Browser einen Film nicht (z. B. Firefox bei x265/AC3), kommt die normale Jellyfin-Meldung.
- Die bisherige Hilfe (Ton umpacken + Butchies-Web-Player) ist nicht gelöscht: Dashboard → Plugins → „Browser-Hilfe (x265/Kino-Ton)“ (Standard: aus).

## 18.11.2026 – Butchies Media Center 3.9.2: Player wie Jellyfin, Untertitel, Designs
- Butchies-Player sieht jetzt aus wie der Jellyfin-Player (alle Knöpfe unten, keine Knöpfe in der Mitte, „Endet um“, Herz, Ton-/Untertitel-Menü).
- Startet sofort von selbst; der Ton kommt mit dem ersten Tippen/Klicken dazu (Hinweis „Für Ton tippen“), ohne dass der Film anhält.
- Doppelklick (Handy: Doppeltippen) = Vollbild; Einfachklick = Pause/Weiter.
- Untertitel: die in Jellyfin gewählte Untertitel- und Tonspur wird übernommen; Bild-Untertitel (PGS/Blu-ray) werden jetzt angezeigt.
- Dashboard → Branding: eigenes CSS wird gespeichert und angewendet (Jellyfin-Designs/Themes per @import).
- Adresse von unterwegs wird richtig gemeldet (LocalAddress über Port 8920).

## 18.11.2026 – Butchies Media Center 3.9.1: Streamen von unterwegs
- Neu: Zugriff von unterwegs über https://butchies-groove.duckdns.org:8920 (verschlüsselt, mit dem Zertifikat der Website). Einschalten mit einem Befehl, danach Portfreigabe 8920 im Router.
- Login-Sperre erkennt auch über diese Tür die richtige Adresse.
- Plugin umbenannt in „Butchies-Player-Aussehen“ (nur Optik; der x265-Player startet automatisch).

## 18.11.2026 – Butchies Media Center 3.9.0: Butchies-Player im Browser
- Neuer eigener Player im Browser: spielt x265/HEVC (auch 10 Bit), H.264 und Kino-Ton (AC3, DTS, TrueHD) ab – entschlüsselt wird auf deinem PC/Handy, das NAS schickt nur die Originaldatei (Direktstream).
- Startet automatisch, wenn der Browser einen Film nicht selbst abspielen kann.
- Mit Spulen (10 s zurück / 30 s vor), Tonspur- und Untertitelwahl, Vollbild, „Weiterschauen“-Position.

## 18.11.2026 – Butchies Media Center 3.8.1: x265 im Browser
- x265/HEVC-Filme werden jetzt immer versucht (viele Browser können HEVC über die Grafikkarte, melden es aber nicht).
- Kann der Browser es wirklich nicht, kommt keine Endlosschleife mehr, sondern ein klarer Hinweis, womit es klappt (Windows-Player, Edge, Apps).

## 18.11.2026 – Butchies Media Center 3.8.0: Identifizieren, Bearbeiten, Künstler, Wiedergabelisten, Sammlungen
- „Identifizieren“: falsch erkannte Filme/Serien über die TMDB-Suche richtig zuordnen.
- „Metadaten bearbeiten“: Titel, Beschreibung, Genres, Jahr, FSK, Schauspieler selbst ändern (wird separat gespeichert, Dateien bleiben unverändert).
- Musik: Künstler werden aus der Ordnerstruktur erkannt (Künstler/Album), eigener Bereich „Künstler“.
- Wiedergabelisten (pro Benutzer) und Sammlungen (für alle) anlegen, füllen, sortieren, löschen.
- Kleinere Fehler in den Einstellungsseiten behoben.

## 18.11.2026 – Butchies Media Center 3.7.0: Ersteinrichtung & Live-Verbindung
- Neue Installation: Einrichtungsassistent im Browser (Sprache, erstes Admin-Konto, Bibliotheken) – kein PuTTY mehr nötig. Nur aus dem Heimnetz und nur solange noch nicht eingerichtet.
- Live-Verbindung zwischen Server und Geräten: „Gesehen“, Favoriten und Fortschritt erscheinen sofort auf allen Geräten.

## 18.11.2026 – Butchies Media Center 3.6.0: Filmplakate & Beschreibungen
- Liest .nfo-Dateien vollständig (Beschreibung, Genres, Schauspieler, Regie, Altersfreigabe) und Hintergrundbilder (fanart.jpg) neben den Filmen und im Serienordner.
- Neu unter Dashboard → Plugins: „TMDb-Metadaten“ – mit eigenem kostenlosen Schlüssel kommen Plakate, Hintergründe, Logos, Beschreibungen, FSK, Schauspieler mit Foto sowie Folgentitel und -bilder automatisch aus dem Internet.
- Eigene Dateien haben immer Vorrang, nichts an den Filmen wird verändert.
- Menüpunkt „Metadaten aktualisieren“ gleicht einen Film/eine Serie neu ab.

## 18.11.2026 – Butchies Media Center 3.5.1: Original-Aussehen
- Player und Filmseite sehen wieder aus wie im Original-Jellyfin.
- Der Butchies-Player bleibt erhalten und lässt sich unter Dashboard → Plugins → „Butchies-Player“ einschalten.
- Untertitel und die Reparatur am Fortsetzen bleiben.

## 18.11.2026 – Butchies Media Center 3.5.0: Untertitel
- Untertitel-Dateien neben dem Film werden automatisch erkannt (z. B. „Film.de.srt“, „Film.forced.ass“), Sprache aus dem Dateinamen.
- Eingebaute Untertitel in MKV/MP4 (SRT, ASS, Blu-ray-PGS) sind auswählbar.
- Erzwungene Untertitel (nur Fremdsprache) schalten sich automatisch ein.
- Untertitel bleiben nach dem Spulen synchron und rutschen über die Steuerleiste.

## 18.11.2026 – Butchies Media Center 3.4.0: Player-Aussehen
- Player: Logo bzw. Filmname oben links, Jahr + Titel unten links, Restzeit „-Rest / Gesamt“, Knöpfe 10 s zurück / 30 s vor, neuer Stopp-Knopf.
- Filmseite: deutlich beschriftete Knöpfe „Fortsetzen“ und „Von Anfang an“.
- Fast fertig geschaute Filme starteten am Ende und brachen sofort ab – jetzt zählen sie ab 90 % als gesehen und starten von vorne.
- Filmtitel aus Dateinamen werden gesäubert („Allen.2026.German.WEBRip…“ → „Allen“ 2026).

## 18.11.2026 – Butchies Media Center 3.3.1
- Vorspulen bei umgepackten Filmen (MKV, Kino-Ton) repariert: Der Film startete nach dem Spulen wieder am Anfang, während die Leiste eine andere Zeit zeigte.

## 18.11.2026 – Butchies Media Center 3.3.0: x265 und Kino-Ton
- Eigenes kleines FFmpeg für das NAS: MKV-Filme werden für den Browser in MP4 umgepackt (Bild unverändert, auch x265/HEVC), Kino-Ton (AC3/E-AC3/DTS/TrueHD) wird in normalen Ton umgewandelt. x265 im Browser braucht Chrome/Edge (bzw. Firefox ab 134 unter Windows 11) mit passender Grafik.
- Das Media Center antwortet jetzt auch per http:// (für die Jellyfin-Apps auf Handy/TV), Browser weiter per https://.

## 18.11.2026 – Butchies Media Center 3.2.0: Verwaltung
- Jellyfin-Verwaltungsbereich funktioniert: Benutzer anlegen, umbenennen, löschen, Admin-Rechte, Passwort ändern; Bibliotheken anlegen, umbenennen, löschen, Ordner per Ordnerauswahl (nur im Medienordner) hinzufügen/entfernen; „Alle Bibliotheken scannen“. Bibliotheks-Kacheln zeigen ein Bild.

## 18.11.2026 – Butchies Media Center 3.1.0: Jellyfin-Oberfläche
- Die originale Jellyfin-Weboberfläche läuft jetzt auf dem eigenen Python-Server (`jf_api.py`): Anmelden, Bibliotheken, Filme, Serien mit Staffeln, Musik-Alben, Poster, Abspielen im Browser, Weiterschauen, Gesehen, Favoriten, Suche. Laufzeit und Tonspuren werden ohne ffprobe aus den Dateien gelesen. Alte Oberfläche entfernt.

## 18.11.2026 – Media Center 3.0.1
- Knopf „Konfigurieren“ im WD-Dashboard führt jetzt zur Startseite statt zu „NOT_FOUND“.

## 18.11.2026 – Butchies Media Center 3.0.0 (Python, wieder lauffähig)
- Jellyfin (.NET) läuft auf dem WD-NAS nicht (32-KB-Speicherseiten). Das eigene Python-Media-Center (Stand 1.0.35) ist jetzt im Repo (`nas/mediacenter/`) und kommt als 3.0.0 zurück; Grundlage für den Einbau der Jellyfin-Funktionen. Jellyfin-Starter-App nach `nas/wd-app/jellyfin-launcher/` verschoben.

## 18.11.2026 – Media Center: Absturz-Diagnose
- Jellyfin stürzte auf dem NAS mit Exit 139 ohne Ausgabe ab → `start-in-container.sh` testet jetzt mehrere .NET-Einstellungen mit `--version`, schreibt das Ergebnis nach `jellyfin/log/diagnose.txt` und startet mit der ersten funktionierenden (App 2.0.3).

## 18.11.2026 – Media Center 2.0.2
- Beim App-Update wird der Jellyfin-Container nicht mehr gelöscht, nur angehalten (spart die 10–15 Min Neueinrichtung).

## 18.11.2026 – Media Center 2.0.1: passende Web-Oberfläche
- Das Jellyfin-Paketlager lieferte Web 10.11 zum Server 10.10 → jetzt wird die Web-Oberfläche passend zur Server-Version installiert (auch nachträglich im laufenden Container).

## 18.11.2026 – WD-App Butchies Media Center 2.0.0 (Jellyfin)
- Neue Version der WD-App ersetzt den alten Python-Server: startet Jellyfin im Docker-Container auf Port 8097, Start/Stopp über das WD-Dashboard, Dashboard-Seite mit Status. Paket: `nas/wd-app/dist/butchiesmediacenter_2.0.0_EX2Ultra.bin`, Bau mit `nas/wd-app/build.sh`.

## 17.11.2026 – Media Center: Jellyfin per Paketlager
- Download-Adresse für 10.10.7 gab 404 → Jellyfin wird jetzt als Debian-Paket (`jellyfin-server`, `jellyfin-web`) aus repo.jellyfin.org installiert.

## 17.11.2026 – Media Center: Jellyfin 10.10.7
- Eigener 10.11-Build braucht neueres glibc als Debian 11 („GLIBC_2.34 not found“) → vorerst offizielles Jellyfin 10.10.7 (.NET 8); Programmdateien werden bei Versionswechsel automatisch ersetzt, Daten bleiben.

## 17.11.2026 – Media Center: install.sh Reihenfolge
- Alter Container wird jetzt vor der Port-Prüfung entfernt (er belegte selbst Port 8099).

## 17.11.2026 – Media Center: Debian-11-Archiv
- Debian 11 wird nicht mehr gepflegt, manche Pakete fehlen auf deb.debian.org (Fehler 404) → `start-in-container.sh` schaltet dann automatisch auf archive.debian.org um.

## 17.11.2026 – Media Center: Debian 11 statt 12
- Debian 12 startet auf dem WD-NAS nicht (64-KB-Speicherseiten, Fehler „ELF … not page-aligned“) → `install.sh` nutzt `arm32v7/debian:bullseye-slim` wie die Website. FFmpeg kommt jetzt als `jellyfin-ffmpeg` aus dem Jellyfin-Paketlager (Debian-11-ffmpeg 4.3 ist für Jellyfin zu alt).

## 17.11.2026 – Media Center auf Port 8099
- Port 8097 war auf dem NAS schon von einem Python-Programm belegt → `nas/jellyfin/install.sh` nutzt jetzt 8099 und prüft vor dem Start, ob der Port frei ist.

## 17.11.2026 – Butchies Media Center (Jellyfin) für ARMv7
- Eigener Build in `Butchies/jellyfin` (Jellyfin 10.11.11 für 32-Bit-ARM, im Emulator gestartet). `nas/jellyfin/start-in-container.sh` lädt jetzt den neuesten eigenen Build, setzt `DOTNET_EnableWriteXorExecute=0`.


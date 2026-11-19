# Butchies Media Center – Player, vollständiger Aufbau und Integrationsplan

## Herkunft der Untersuchung
Untersucht wurde das bereitgestellte Serverpaket Version 4.10.2.0. Die Datei `REFERENZ_INVENTAR.json` erfasst 52 tatsächlich vorhandene Player- und Einstellungsdateien aus dessen Weboberfläche. Die Originaldateien sind **nicht** im Lieferpaket enthalten. HTML, CSS, JavaScript und diese Dokumentation sind neu geschrieben.

## 1. Festgestellte Modulgruppen
- **Video-Bedienoberfläche:** `videoosd/videoosd.html`, `videoosd/videoosd.js`, `videoosd/videoosd.css`, `videoosd/videoosd_tv.css`, `videoosd/videoosd_nontv.css`
- **Informationsreiter:** `videoosd/infotab.js`, `videoosd/peopletab.js`, `videoosd/chapterstab.js`, `videoosd/playqueuetab.js`, `videoosd/guidetab.js`, `videoosd/onnowtab.js`
- **Wiedergabesteuerung:** `modules/common/playback/playbackmanager.js`, `modules/common/playback/playqueuemanager.js`, `modules/common/playback/playersettingsmenu.js`, `modules/common/playback/sleeptimermenu.js`
- **Browser-Videoengine:** `modules/htmlvideoplayer/plugin.js`, `modules/htmlvideoplayer/basehtmlplayer.js`, `modules/htmlvideoplayer/htmlmediahelper.js`
- **Audio:** `modules/htmlaudioplayer/plugin.js`
- **Sitzung, Gerät und Oberfläche:** `modules/playback/currentplayer.js`, `modules/playback/mediasession.js`, `modules/playback/osdcontroller.js`, `modules/playback/playerselection.js`, `modules/sessionplayer.js`
- **Weitere Komponenten:** `modules/playerstats/playerstats.js`, `modules/subtitleoffsetdialog/subtitleoffsetdialog.js`, `modules/subtitleappearancedialog/subtitleappearancedialog.js`, `modules/chromecast/chromecastplayer.js`
- **Einstellungen:** `settings/playback.html`, `settings/playback.js`, `settings/appplayback.html`, `settings/appplayback.js`, `settings/subtitles.html`, `settings/subtitles.js`

Die Zuordnung basiert auf den vorhandenen Dateipfaden und in ausgewählten JS-Dateien nachweisbaren Methoden. Die exakte interne Serverimplementierung lässt sich aus diesen Webmodulen allein nicht vollständig rekonstruieren.

## 2. Bedienoberfläche
```text
Player
├── Videofläche / Bild-im-Bild / Vollbild
├── Bildschirmsteuerung (OSD)
│   ├── Zeitleiste / Kapitelmarken
│   ├── Vorheriges / Zurückspulen / Play-Pause / Vorspulen / Nächstes
│   ├── aktuelle Position / Dauer
│   ├── Lautstärke / Stumm
│   ├── Audio- und Untertitelwahl
│   ├── Qualität / Wiedergabegeschwindigkeit
│   ├── Einstellungen / Statistiken
│   └── Warteschlange / nächste Folge
├── Infobereich
│   ├── Titel / Handlung / Medieninformation
│   ├── Besetzung / Team
│   ├── Kapitel
│   └── Warteschlange
└── Systemebene
    ├── Geräteauswahl / Sitzungssteuerung
    ├── Wiedergabefortschritt
    ├── Sleep-Timer
    └── Wiedergabefehler / Berechtigungen
```
Welche Steuerelemente im jeweiligen Client tatsächlich angezeigt werden, hängt von Wiedergabeart und Gerätefähigkeiten ab.

## 3. Datenfluss und Verknüpfungen
```text
Film-Detailseite (media.id)
  -> POST /api/playback/{id}/session
  -> Server prüft Benutzer, Quelle, Spuren und Gerät
  -> Server liefert session_id, media_source_id, duration, stream_url,
     audio_tracks, subtitle_tracks, chapters, resume_position
  -> Browser-Player lädt stream_url
  -> PUT /api/playback/sessions/{session_id}/progress
  -> POST /api/playback/sessions/{session_id}/stop
  -> Benutzerstatus und Fortsetzen werden gespeichert
```
**Die `/api/…`-Routen sind eigene Entwürfe für Butchies, keine aus dem untersuchten Paket behaupteten Originalrouten.**

## 4. Wiedergabeentscheidungen
1. **Direkte Wiedergabe:** Container, Video-Codec, Audio-Codec und Untertitel sind vom Client vollständig unterstützt.
2. **Direkter Stream / Remux:** Video-/Audiocodecs sind kompatibel, aber der Container muss ohne Neucodierung umgepackt werden.
3. **Transcoding:** Nur wenn Server und Gerät ausreichend Leistung besitzen und die Funktion aktiviert ist. Auf dem WD My Cloud EX2 Ultra muss die geringe Hardwareleistung berücksichtigt werden.
4. **4K-Sperre:** Für das NAS-Profil muss 4K-Wiedergabe blockiert und mit verständlichem Hinweis versehen werden. HEVC/H.265-Unterstützung ist vom jeweiligen Wiedergabegerät abhängig.
5. **Fehlerfall:** Codec-, Netzwerk- und Berechtigungsfehler getrennt behandeln.

Die Vorschau in diesem ZIP nutzt ausschließlich die native Browser-Media-Engine. Sie enthält **kein** Remuxing, keine Transcodierung und keinen NAS-Streamserver.

## 5. Vollständige Player-Schnittstellen (Soll-Architektur)
| Methode | Route | Zweck |
|---|---|---|
| POST | `/api/playback/{id}/session` | Wiedergabe beginnen und Quelle wählen |
| GET | `/api/playback/sessions/{id}` | Sitzung und Fähigkeiten |
| PUT | `/api/playback/sessions/{id}/progress` | Position, Pause, Lautstärke |
| POST | `/api/playback/sessions/{id}/stop` | Wiedergabe beenden |
| GET | `/api/playback/{id}/stream` | Dateistream mit HTTP-Range |
| GET | `/api/playback/{id}/subtitles/{trackId}` | Untertitel abrufen |
| GET | `/api/playback/{id}/chapters` | Kapitel |
| GET | `/api/playback/{id}/sources` | Dateiversionen und Spuren |
| GET | `/api/playback/{id}/next` | Nächste Episode |
| GET | `/api/users/me/playback-settings` | Einstellungen |
| PUT | `/api/users/me/playback-settings` | Einstellungen speichern |
| GET | `/api/devices` | Geräteübersicht |

Streamzugriff nur mit gültiger Autorisierung, Berechtigungsprüfung und Unterstützung für `Range`, `206 Partial Content`, `Content-Range` und Abbruch des Streams. Niemals einen beliebigen Dateipfad aus Clientparametern öffnen.

## 6. Beispiel einer Session-Antwort
```json
{
  "session_id": "session-123",
  "media_id": "film-0001",
  "media_source_id": "source-1",
  "stream_url": "/api/playback/film-0001/stream?source=source-1",
  "duration_ms": 6420000,
  "resume_position_ms": 120000,
  "delivery": "direct",
  "video_codec": "hevc",
  "audio_tracks": [{"id": "audio-1", "language": "de", "codec": "aac"}],
  "subtitle_tracks": [{"id": "sub-1", "language": "de", "format": "vtt"}],
  "chapters": [{"title": "Kapitel 1", "start_ms": 0}],
  "next_media_id": null
}
```

## 7. Datenbank-Erweiterung für Wiedergabe
```sql
CREATE TABLE IF NOT EXISTS playback_sessions (
 id TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 media_id TEXT NOT NULL REFERENCES media(id) ON DELETE CASCADE,
 media_file_id TEXT REFERENCES media_files(id),
 device_id TEXT,
 started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 last_progress_at TEXT,
 position_ms INTEGER NOT NULL DEFAULT 0,
 paused INTEGER NOT NULL DEFAULT 0,
 stopped_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_playback_user ON playback_sessions(user_id,stopped_at);
CREATE TABLE IF NOT EXISTS playback_preferences (
 user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
 default_audio_language TEXT,
 default_subtitle_language TEXT,
 autoplay_next INTEGER NOT NULL DEFAULT 1,
 preferred_quality TEXT NOT NULL DEFAULT 'auto',
 subtitle_size TEXT NOT NULL DEFAULT 'medium',
 subtitle_offset_ms INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS playback_queue (
 session_id TEXT NOT NULL REFERENCES playback_sessions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL,
 media_id TEXT NOT NULL REFERENCES media(id),
 PRIMARY KEY(session_id,position)
);
```

## 8. Dateien der eigenen Vorschau
- `index.html`: Oberfläche mit Video, Steuerleiste, Einstellungen und Warteschlange
- `player.css`: eigenständige Gestaltung und responsive Anordnung
- `player.js`: Dateiöffnung, Play/Pause, Seek, Lautstärke, Tempo, VTT-Untertitel, Vollbild, Bild-im-Bild, Warteschlange, Autoplay, lokale Fortsetzen-Position, Tastenkürzel
- `player-schema.sql`: eigene SQLite-Erweiterung für Wiedergabesitzungen
- `REFERENZ_INVENTAR.json`: nachvollziehbare Liste untersuchter Quelldateien

## 9. Grenzen der Vorschau
- Lokale Dateien werden über die Dateiauswahl des Browsers geöffnet; keine NAS-Anbindung.
- Nicht jeder Browser kann HEVC, MKV oder FLAC wiedergeben.
- Die Tonspurwahl ist ein Platzhalter, da die Browser-Media-API keine einheitliche Auswahl aller eingebetteten Spuren garantiert.
- Untertitel-Versatz ist nur als UI-Feld vorhanden; noch keine zeitliche Korrektur implementiert.
- Die Vorschau zeigt keine serverseitigen Kapitel, keine externe Gerätesteuerung, keine Statistiken und keinen Autoplay-Countdown.
- Wiedergabefortschritt wird lokal im Browser gespeichert, nicht in der Butchies-Datenbank.
- Es wurde nichts in GitHub oder auf dem NAS installiert.

**Fazit:** Vollständiger untersuchungsbasierter Architektur- und Integrationsbauplan mit einer funktionierenden lokalen Browser-Player-Vorschau. Nicht mit einem bereits vollständig implementierten NAS-Medienplayer verwechseln.

# Hinweise für Claude – Butchies Media Center

- **Hauptquelle des Media Centers ist dieses Projekt** (seit 19.11.2026). Der alte Ordner `nas/mediacenter/butchiesmediacenter/` im privaten Projekt Butchies/butchies-raucherstube ist veraltet.
- Ausführliche Entwicklungsnotizen (Aufbau, IDs, Phasen, Messungen) stehen im privaten Projekt `Butchies/butchies-raucherstube` in `CLAUDE.md` (Abschnitt „Butchies Media Center 3.x“).
- Nutzer schreibt Deutsch, ist technisch unerfahren → einfach erklären. Jede Antwort endet mit Fortschritt in % + nächster Phase, „🔄 Website-Update bereit“ und „📱 Neue APK nötig“.
- **Nie selbst Medienordner freigeben** – Bibliotheken legt nur der Nutzer an.
- Kein Emby-Code kopieren. Keine Geheimnisse ins Projekt (öffentlich!).
- Einschränkungen (z. B. Firefox kann x265/DTS/AC3 nicht) dem Nutzer immer sofort klar sagen.
- Ablauf: Änderung in `app/` → Versionsnummer in `app/apkg.rc`, `app/apkg.xml`, `app/server.py` erhöhen → Eintrag oben in `CHANGELOG.md` → push auf `main` → Workflow „WD-App bauen“ legt die `.bin` unter Releases ab. Nutzer installiert selbst (WD-Dashboard → Apps → Manuell installieren). Neue Versionen erst nach komplett abgeschlossener Phase.
- Lokal testen: `BMC_DATA=… BMC_MEDIA=… BMC_PORT=18099 python3 app/server.py`, Playwright + `/usr/bin/google-chrome`, Desktop und Handy (360 px).

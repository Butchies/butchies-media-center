# Butchies Media Center – Film-Detailseite

## Ziel
Eigenständig entwickelte Filmansicht für Butchies Media Center. Die mitgelieferten Dateien enthalten ausschließlich neu geschriebenen Beispielcode und frei erfundene Demodaten. Es werden keine Dateien anderer Medienserver übernommen.

## Seitenstruktur
1. **Navigation:** Zurück, Startseite, Filme, Serien, Suche, Profil.
2. **Hintergrund:** großflächiges Filmbild, dunkler Verlauf für lesbare Texte.
3. **Film-Kopfbereich:** Hochformatposter, Titel, Erscheinungsjahr, Laufzeit, Altersfreigabe, Genres und Bewertung.
4. **Hauptaktionen:** Abspielen, Fortsetzen (bei gespeichertem Fortschritt), Trailer, Favorit, Gesehen, Weitere Aktionen.
5. **Spurauswahl:** Videoquelle, Tonspur und Untertitel, sofern verfügbar.
6. **Beschreibung:** Kurzfassung, vollständige Inhaltsbeschreibung und Regie.
7. **Reiter:** Übersicht, Darsteller, Extras, Kapitel, Ähnliche Titel, Medieninformationen.
8. **Darstellerkarten:** Personendetails über eine eigene Personenseite.
9. **Extras:** Trailer und Zusatzvideos über die Playeransicht.
10. **Kapitel:** Sprungmarken zur Wiedergabezeit.
11. **Ähnliche Filme:** Karten mit Verlinkung zur jeweiligen Film-Detailseite.
12. **Mediendaten:** Container, Bildformat, Auflösung, Codec, Bildrate, Tonspuren und Untertitel.
13. **Kontextmenü:** In Sammlung, Zur Wiedergabeliste, Bilder bearbeiten, Metadaten bearbeiten, Download (nur bei Berechtigung).

## Eigene Module
| Datei | Aufgabe |
|---|---|
| `index.html` | Eigenständige interaktive Designvorschau mit Beispieldaten |
| `movie-detail.css` | Layout, responsives Verhalten, Farben, Karten und Bedienelemente |
| `movie-detail.js` | Renderlogik, Tabs, Menüs, Navigation, Aktionen und Demo-Zustand |
| `integration.md` | Benötigte Serverdaten, API-Verträge und Verlinkungen |

## Anzeige-Bedingungen
- Fortsetzen erscheint nur bei Wiedergabefortschritt zwischen 0 und 100 Prozent.
- Trailer, Extras, Kapitel, Darsteller, ähnliche Titel und Spurauswahl erscheinen nur bei vorhandenen Daten.
- Die Download-Funktion erscheint nur mit entsprechender Benutzerberechtigung.
- Poster und Hintergrund haben unabhängige Bildquellen und einen neutralen Platzhalter.
- Bildformat und Kartengröße sind unabhängig voneinander.

## Vorschau
`index.html` im Browser öffnen. Die Demo benutzt erfundene Film- und Personendaten. Aktionen zeigen beispielhaft die Navigation und Interaktion, nicht die echte Serveranbindung.

# Butchies Media Center – Daten- und Navigationsvertrag

## Navigation
- `#/movie/{id}`: Detailseite eines Films.
- `#/person/{id}`: Personendetailseite.
- `#/play/{id}?t={sekunden}`: Wiedergabe mit optionalem Startzeitpunkt.
- `#/collection/{id}`: Sammlung.
- `#/edit-images/{id}`: Eigene Bildverwaltung.
- `#/edit-metadata/{id}`: Eigener Metadateneditor.
- `#/search?q={suchtext}`: Suche.

Diese Routen sind **vorgeschlagene eigene Schnittstellen**, nicht bereits bestehende Server-Endpunkte. Sie müssen beim Einbau an den tatsächlichen Router angepasst werden.

## Erwartete Filmdaten
`id`, `title`, `year`, `runtimeMinutes`, `ageRating`, `genres[]`, `rating`, `overview`, `tagline`, `directors[]`, `posterUrl`, `backdropUrl`, `progressSeconds`, `durationSeconds`, `isFavorite`, `isPlayed`, `canDownload`, `sources[]`, `audioTracks[]`, `subtitleTracks[]`, `people[]`, `trailers[]`, `extras[]`, `chapters[]`, `similar[]`, `technical`.

## Erforderliche Backend-Funktionen
- Film lesen: `GET /api/movies/{id}`
- Bild abrufen: `GET /api/movies/{id}/images/{type}`
- Ähnliche Titel: `GET /api/movies/{id}/similar`
- Favorit speichern: `PUT /api/users/me/favorites/{id}`
- Gesehen speichern: `PUT /api/users/me/played/{id}`
- Fortschritt speichern: `PUT /api/users/me/progress/{id}`
- Abspielinformationen: `GET /api/movies/{id}/playback`
- Trailer und Extras: `GET /api/movies/{id}/extras`
- Bilder verwalten: `GET/POST/DELETE /api/movies/{id}/images`

Alle Endpunkte sind **Entwürfe für die eigene Implementierung**, keine Behauptung über vorhandene Funktionen.

## Darstellungslogik
- Filmplakat: `object-fit: contain` oder `cover`, je nach Ansicht.
- Hintergrund: `background-size: cover` plus Farbverlauf.
- Karten: Poster 2:3, Video 16:9, Musik 1:1, weitere Formate nach Metadaten.
- Alle Eingaben müssen serverseitig geprüft werden. Schreibaktionen brauchen Benutzerberechtigungen und Authentifizierung.

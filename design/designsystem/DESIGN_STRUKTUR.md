# Butchies Media Center – vollständige Designanalyse

## Untersuchungsgrundlage
Ausgewertet wurde das bereitgestellte Serverpaket Version 4.10.2.0. Diese Dokumentation ist neu formuliert. Es sind keine fremden Quelldateien enthalten.

## Gefundene Designvarianten

### Helles Oberflächendesign (`light`)

- Hintergrund-/Systemfarbe: `#ffffff`
- Systemdarstellung: `light`
- Fensterleiste: `#e9e9e9`
- Fenstertitel: `#222222`
- Statusleistenschrift: `dark`
- Navigationsleistenschrift: `dark`
- Bestandteile:
  - `theme_nontv.css` (789 Byte)
  - `theme_tv.css` (3,565 Byte)
  - `theme.json` (230 Byte)
  - `theme.css` (28,638 Byte)

### Dunkles Design mit Verlauf und Hintergrundgrafik (`darkgradient`)

- Hintergrund-/Systemfarbe: `#141414`
- Systemdarstellung: `dark`
- Fensterleiste: `#001935`
- Fenstertitel: `#dddddd`
- Statusleistenschrift: `light`
- Navigationsleistenschrift: `light`
- Bestandteile:
  - `blueradiance.jpg` (1,044,963 Byte)
  - `theme_nontv.css` (760 Byte)
  - `theme_tv.css` (3,352 Byte)
  - `theme.json` (304 Byte)
  - `theme.css` (33,127 Byte)

### Schwarzes Oberflächendesign (`black`)

- Hintergrund-/Systemfarbe: `#000`
- Systemdarstellung: `dark`
- Fensterleiste: `#1c1c1c`
- Fenstertitel: `#dddddd`
- Statusleistenschrift: `light`
- Navigationsleistenschrift: `light`
- Bestandteile:
  - `theme_nontv.css` (1,099 Byte)
  - `theme_tv.css` (3,565 Byte)
  - `theme.json` (301 Byte)
  - `theme.css` (29,633 Byte)

### Helles, TV-orientiertes Oberflächendesign (`appletv`)

- Hintergrund-/Systemfarbe: `#ADBEC2`
- Systemdarstellung: `light`
- Fensterleiste: `#d7e4eb`
- Fenstertitel: `#222222`
- Statusleistenschrift: `dark`
- Navigationsleistenschrift: `dark`
- Bestandteile:
  - `theme_nontv.css` (760 Byte)
  - `theme_tv.css` (3,088 Byte)
  - `theme.json` (230 Byte)
  - `theme.css` (30,566 Byte)

### Dunkles Standarddesign (`dark`)

- Hintergrund-/Systemfarbe: `#141414`
- Systemdarstellung: `dark`
- Fensterleiste: `#282828`
- Fenstertitel: `#dddddd`
- Statusleistenschrift: `light`
- Navigationsleistenschrift: `light`
- Bestandteile:
  - `theme_nontv.css` (1,616 Byte)
  - `theme_tv.css` (4,160 Byte)
  - `theme.json` (304 Byte)
  - `theme.css` (29,891 Byte)
  - `theme_tv_nocssvars.css` (29,223 Byte)

## Aufbau und Verknüpfungen

Die zentrale Designverwaltung lädt ein gewähltes Design und dessen Stylesheets. Die jeweilige Konfiguration bestimmt unter anderem Fensterfarben und Hell-/Dunkelmodus.
Pro Design sind ein Basis-Stylesheet, ein TV-Stylesheet und ein Desktop-/Mobil-Stylesheet vorhanden. Einige Designs ergänzen Grafiken oder Fallback-CSS.
Die Routensteuerung kann zwischen normaler und horizontaler TV-Startseite wechseln. Die Gestaltung greift auf gemeinsame Layout-, Karten-, Dialog-, Navigations- und Detailseiten-Styles zurück.

### Relevante Quelldatei-Gruppen und Abhängigkeiten

#### Designverwaltung
5 Dateien im Paket gefunden.
- `modules/skinmanager.js`
- `modules/cssloader.js`
- `modules/themes/themecontroller.js`
- `modules/common/usersettings/usersettings.js`
- `modules/common/appsettings.js`

#### Layout
30 Dateien im Paket gefunden.
- `modules/themes/common/darkcontentcontainer_nontv.css`
- `modules/themes/common/darkcontentcontainer_item.css`
- `modules/themes/common/darkcontentcontainer.css`
- `modules/themes/common/darkcontentcontainer_tv.css`
- `modules/layout/layout_nontv_rtl.css`
- `modules/layout/layout_nontv.css`
- `modules/layout/layout_rtl.css`
- `modules/layout/layout_tv.css`
- `modules/layout/layout_nocssvars.css`
- `modules/layout/layout_tv_rtl.css`
- `modules/layout/layout.css`
- `modules/cardbuilder/card_nontv.css`
- `modules/cardbuilder/card_sizes_base.css`
- `modules/cardbuilder/card_post.css`
- `modules/cardbuilder/card_sizes_horizontal_var.css`
- `modules/cardbuilder/card_sizes_varcalcmax.css`
- `modules/cardbuilder/cardpadder_legacy.css`
- `modules/cardbuilder/card_tv2.css`
- `modules/cardbuilder/cardbuilder.js`
- `modules/cardbuilder/card_nontv2.css`
- `modules/cardbuilder/card_tv3.css`
- `modules/cardbuilder/card_sizes_horizontal_base.css`
- `modules/cardbuilder/card_sizes_horizontal_all.css`
- `modules/cardbuilder/card_sizes_container.css`
- `modules/cardbuilder/card.css`
- `modules/cardbuilder/card_sizes_var.css`
- `modules/cardbuilder/card_sizes_horizontal_varcalcmax.css`
- `modules/cardbuilder/card_sizes_horizontal_container.css`
- `modules/backdrop/style.css`
- `modules/backdrop/backdrop.js`

#### Startseite
6 Dateien im Paket gefunden.
- `home/home.js`
- `home/favorites.js`
- `home/hometab.js`
- `home/home.html`
- `home_horiz/home.js`
- `home_horiz/home.html`

#### Filmseite
5 Dateien im Paket gefunden.
- `item/linkeditems.js`
- `item/item_2_tv.css`
- `item/item.css`
- `item/item.js`
- `item/item.html`

#### Wiedergabe
1 Dateien im Paket gefunden.
- `modules/thememediaplayer.js`

#### Bilder
18 Dateien im Paket gefunden.
- `modules/common/imagehelper.js`
- `modules/cardbuilder/card_nontv.css`
- `modules/cardbuilder/card_sizes_base.css`
- `modules/cardbuilder/card_post.css`
- `modules/cardbuilder/card_sizes_horizontal_var.css`
- `modules/cardbuilder/card_sizes_varcalcmax.css`
- `modules/cardbuilder/cardpadder_legacy.css`
- `modules/cardbuilder/card_tv2.css`
- `modules/cardbuilder/cardbuilder.js`
- `modules/cardbuilder/card_nontv2.css`
- `modules/cardbuilder/card_tv3.css`
- `modules/cardbuilder/card_sizes_horizontal_base.css`
- `modules/cardbuilder/card_sizes_horizontal_all.css`
- `modules/cardbuilder/card_sizes_container.css`
- `modules/cardbuilder/card.css`
- `modules/cardbuilder/card_sizes_var.css`
- `modules/cardbuilder/card_sizes_horizontal_varcalcmax.css`
- `modules/cardbuilder/card_sizes_horizontal_container.css`

## Neu geschriebenes Butchies-Designsystem

Die folgenden sechs Designvarianten sind eigenständige Neuformulierungen und keine Kopien der untersuchten Stylesheets.
Alle Varianten verwenden dieselben Komponenten: Navigation, Kopfzeile, Kachelraster, Film-Detailbereich, Dialoge, Eingabefelder und Player-Overlay.
Die Dateien im Unterordner `themes/` enthalten die vollständigen Farbvariablen. `butchies-ui.css` enthält die gemeinsamen Regeln. `preview.html` dient der Ansicht ohne Server.

### Integrationspunkte

- `data-bmc-theme` am Wurzelelement steuert die Farbauswahl.
- Die Anwendung muss den gespeicherten Designnamen beim Start setzen.
- Die fünf Bildformate werden über `data-shape` (poster, wide, square, classic, banner) gewählt.
- Eine serverseitige Speicherung oder Einbindung in GitHub ist nicht Bestandteil dieses Referenzpakets.

### Abgrenzung

Die Analyse dokumentiert die im Paket nachweisbaren Design-Dateien und Verknüpfungsgruppen. Sie behauptet nicht, dass die neue Vorschau jedes Verhalten der Originaloberfläche vollständig nachbildet.
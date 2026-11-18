# Die fragmentierte Stadt – Innsbruck

Interaktive Karte zum Stadtmodell der **fragmentierten Stadt** nach Axel Borsdorf für Innsbruck und alle Nachbargemeinden (plus Götzens). Gebaut für eine Präsentation in der Oberstufe.

**Live:** https://kingalo7.github.io/fragmentierte-stadt-innsbruck/

Die Karte ist eine einzige Datei, [`index.html`](index.html), in der alle Daten eingebettet sind. Leaflet und die Grundkarten werden aus dem Netz geladen.

## Ansichten

| Tab | Inhalt |
|---|---|
| **Karte** | Inseln der fragmentierten Stadt: Konsum, Gewerbe & Produktion, Wohnen, Bildung & Wissen, Erholung & Freizeit, dazu Barrieren (Autobahn, Bahn, Inn, Flughafen) |
| **Wohnen im Detail** | Heatmap der drei Bauformen des Wohnens: Einfamilienhäuser, Mehrfamilienhäuser und Großwohnanlagen. Mischfarben zeigen gemischte Bebauung |
| **Heatmap** | Dichteoberflächen aller Kategorien: entweder gemischt oder je eine Kategorie einzeln |

Zusätzliche Ebenen:
- **Verkehr:** Belastung jeder Straße über den Tag (Werktag und Wochenende), als Animation
- **Flächenwidmung:** amtliche Widmung
- **Stadtteilgrenzen**

## Methoden (kurz)

### 1. Heatmap (`heat.py`)
- **Raster:** 75 m. Je Zelle werden Indikatoren aufsummiert:
  - Gebäude aus OSM, gewichtet nach Grundfläche oder Geschoßfläche
  - Geschäfte, Lokale, Betriebe, Schulen, Sport- und Spielplätze (POIs)
  - Landnutzungsflächen aus OSM
  - **amtliche Flächenwidmung**, zum Beispiel Gewerbegebiet, Kerngebiet oder Sonderfläche Sport/Grünanlage
- **Wohngebäude:** Gebäude ohne genaue Angabe (`building=yes`) gelten als Wohngebäude, wenn sie in einer Wohn- oder Mischwidmung liegen. Die Bauform hängt dann von Grundfläche und Geschoßzahl ab:
  - Einfamilienhaus: höchstens 260 m² und höchstens 3 Geschoße
  - Großwohnanlage: ab 7 Geschoßen oder ab 1100 m² Grundfläche
  - Mehrfamilienhaus: alles dazwischen
- **Glättung und Normierung:** Gauß-Kerndichte mit σ ≈ 195 m. Jede Kategorie wird auf ihr 99,5-%-Perzentil normiert (= 100 %).
- **Darstellung „Alle Kategorien“:**
  - Der Farbton ist das Mittel der Kategorienfarben, gewichtet mit v³.
  - Die Deckkraft folgt der stärksten Kategorie.
  - So bleiben Übergänge und Mischgebiete sichtbar.

### 2. Inseln / Flächen (`tiris_laden.py`, `bloecke.py`, `inseln.py`)
- **Grundlage:** amtliche Realnutzungskartierung des Landes Tirol (tiris „Landnutzung“, M 1:1000, Stand 1.10.2025). Straßen und Bahn sind dort eigene Flächen, jede Siedlungsfläche ist also ein Baublock zwischen Straßen.
- **Kategorie je Block:**

  | Realnutzung | Kategorie |
  |---|---|
  | Wohnnutzung, Mischnutzung, Anwesen | Wohnen. Gemischte Blöcke mit Kern- oder Handelswidmung und mindestens 6 Geschäften je ha werden Konsum |
  | Industrie und Gewerbe | Gewerbe. Überwiegend als Handel gewidmet: Konsum |
  | Sonstige Nutzung: Handel | Konsum |
  | Grünanlagen, Sport, Golf, Camping, Freizeit | Erholung & Freizeit. Schipisten am Berg sind ausgenommen |
  | Flugverkehr und OSM-Flughafengelände | Barriere |
  | überwiegend als Bildung gewidmet oder OSM-Schul- bzw. Hochschulgelände | Bildung |
  | Sonstige Nutzung, etwa Kliniken | ohne Kategorie |

- **Bauform:** Sie stammt aus den amtlichen Gebäuden (tiris „Gebäude“, Höhe aus Laserscan). Die Geschoßzahl ist die Höhe geteilt durch 3,1 m:
  - Einfamilienhaus: höchstens 260 m² und höchstens 3 Geschoße
  - Großwohnbau: ab 7 Geschoßen, oder ab 1100 m² Grundfläche mit mindestens 4 Geschoßen
  - Mehrfamilienhaus: alles dazwischen
  - Je Insel werden die Anteile nach Geschoßfläche angegeben.
- **Inseln:**
  - Blöcke derselben Kategorie werden über Nebenstraßen hinweg zusammengefasst (bis etwa 24 m Abstand).
  - Hauptstraßen (OSM tertiary und höher), Autobahn, Bahn und Inn trennen sie.
  - Die Inseln werden an Gemeindegrenzen geteilt. Inseln unter 0,25 ha fallen weg.
- **Namen:** Bezeichnung + Ort (+ Bauform) + (Grenzstraßen), etwa „Wohngebiet Pradl – Mehrfamilienhäuser (Andechsstraße – Amraser-See-Straße – Reichenauer Straße)“.
  - **Bezeichnung:** Eigenname aus OSM, wenn ein benanntes Gelände mindestens die halbe Insel ausmacht. Bei Gewerbe zählen Gebietsnamen wie „Gewerbegebiet Roßau“. Sonst steht die genaue Nutzung da.
  - **Ort:** alle OSM-Ortsteile in der Insel, sonst der nächste bis 300 m, sonst Stadtteil oder Gemeinde.
  - **Grenzstraßen:** die bis zu drei benannten Straßen, die die Insel am längsten begleiten.
- **Prüfung:** Die neuen Inseln wurden gegen OSM-Objekte geprüft, die nicht zur Abgrenzung verwendet wurden. Der Anteil, der in der Insel der passenden Kategorie liegt, ist deutlich gestiegen:

  | OSM-Objekte | vorher (Heatmap-Blobs) | jetzt |
  |---|---|---|
  | Parks und Sportplätze | 39 % | 69 % |
  | Industrieflächen | 30 % | 53 % |
  | Einkaufszentren | 55 % | 69 % |
  | Schulen und Hochschulen | 46 % | 71 % |

  Gewerbeinseln sind zu 89 % als Gewerbegebiet gewidmet.
- **Texte:** Handgeschriebene Texte aus `content.json` werden ergänzt, wenn eine Insel derselben Kategorie überlappt.
- `masken.py` (die frühere, heatmap-basierte Abgrenzung) wird nicht mehr verwendet.

### 3. Verkehr (`profiles.py`, `traffic.py`, `verkehrsmodell.py`)
- **Messdaten:**
  - Zählstellen des Landes Tirol: Stundenwerte vom September 2026, Jahreswerte 2024/25
  - ASFINAG-Zählstellen an A12/A13
  - Daraus entstehen mittlere Tagesganglinien je Richtung für Werktag und Wochenende.
- **Modell für alle übrigen Straßen:**
  - **Straßennetz:** aus OSM (Wohnstraßen und größer)
  - **Gravitationsmodell:**
    - Wohnorte: Wohnfläche auf einem 300-m-Raster
    - Ziele: Arbeits- und Versorgungsflächen
    - Beide werden je Gemeinde auf Einwohner und Beschäftigte von Statistik Austria skaliert.
  - Dazu kommen Einfallstraßen und Autobahn-Anschlüsse als Quellen und Ziele.
  - **Umlegung:** auf kürzeste Wege (Dijkstra) mit Kapazitätsbeschränkung (BPR, 2 Iterationen)
- **Kalibrierung:**
  - Robuste nicht-negative Kleinste-Quadrate-Anpassung (NNLS) an 39 Zählwerte, Rohmodell R² ≈ 0,79
  - Danach eine lokale Korrektur entlang derselben Straße
  - Die Tagesganglinien je Verkehrskomponente (Hinweg, Rückweg, Sonstiges, Durchgang) werden an die gemessenen Stundenwerte angepasst und über 3 Stunden geglättet.
- **Animation:** Die Dichte der Partikel ist proportional zur Verkehrsmenge.

### 4. Flächenwidmung (`widmung.py`)
- Die tiris-Widmung wird in vereinfachte Klassen eingeteilt: Gewerbe, Handel, Kern, Misch, Wohnen, gefördertes Wohnen, Dorf, Bildung, Betrieb, Freizeit, Beherbergung und Sonstiges.
- Freizeit umfasst Grünanlagen, Sport- und Spielplätze, Kleingärten und Golfplätze.
- Sie fließt in Heatmap und Inseln ein und ist auch als eigene Ebene sichtbar. Dazu kommen die EKZ-Zonen der Raumordnung.

## Datenquellen

| Daten | Quelle | Lizenz |
|---|---|---|
| Gebäude, POIs, Landnutzung, Straßen, Grenzen | © OpenStreetMap-Mitwirkende (BBBike-Auszug Innsbruck, 14.11.2026) | ODbL |
| Realnutzung (Landnutzung), Gebäude mit Höhen, Flächenwidmung, Einkaufszentren | Land Tirol – tiris | CC BY 4.0 |
| Verkehrszählung | Land Tirol, ASFINAG | öffentliche Zähldaten |
| Einwohner, Beschäftigte je Gemeinde | Statistik Austria, Abgestimmte Erwerbsstatistik 2024 | CC BY 4.0 |
| Grundkarten | Esri, OpenStreetMap | Nutzungsbedingungen der Anbieter |

Hinweis: Die Widmung ist nicht rechtsverbindlich, verbindlich ist der Plan der Gemeinde. Die Position einiger Zählstellen ist nur ungefähr bekannt.

## Neu bauen

Benötigt Python 3 mit `numpy scipy shapely matplotlib contourpy osmium openpyxl`. Die Rohdaten (OSM-PBF, tiris-Landnutzung und -Gebäude, Zähl-XLSX) liegen nicht im Repo.

```bash
cd werkzeuge
python osm2json.py ibk.osm.pbf roh/                       # Gebäude, POIs, Landnutzung
python widmung.py flw_*.geojson daten/widmung.geojson     # tiris-Widmung
python heat.py roh/bld.json roh/poi.json roh/lu.json daten/heat.json daten/widmung.geojson
python verkehrsmodell.py ibk.osm.pbf roh/bld.json roh/poi.json daten/traffic.json daten/profiles.json daten/netz.json daten/gemeinden_statistik.json
python tiris_laden.py Landnutzung "OBJEKT LIKE 'LN-S%' OR OBJEKT LIKE 'LN-A%' OR OBJEKT='LN-VF'" OBJEKT,KLASSE,GEMNR,STAND roh/landnutzung.geojson
python tiris_laden.py Gebaeude 1=1 GEB_HOEHE_MAX,GEB_HOEHE_MEDIAN,GEMNR roh/gebaeude.geojson
python bloecke.py roh/landnutzung.geojson roh/gebaeude.geojson daten/widmung.geojson roh/lu.json roh/poi.json daten/netz.json lines.geojson daten/bloecke.geojson
python inseln.py daten/bloecke.geojson roh/lu.json roh/poi.json content.json daten/flaechen.json
python bauen.py                                           # -> ../index.html
```

Die aufbereiteten Zwischenergebnisse liegen in `werkzeuge/daten/`. Für Änderungen an der Oberfläche (`vorlage.html`) reicht deshalb `python bauen.py`.

## Deployment

Jeder Push auf `main` veröffentlicht `index.html` über GitHub Actions auf GitHub Pages (`.github/workflows/pages.yml`).

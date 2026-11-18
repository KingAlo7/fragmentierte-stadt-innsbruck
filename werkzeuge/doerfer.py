"""Nachbargemeinden von Innsbruck: Grenzen + generalisierte Flächen aus der OSM-Landnutzung.

Aufruf: python doerfer.py nachbarn_osm.json lu.json ../boundaries.geojson daten/doerfer.json
 - nachbarn_osm.json: Overpass "rel(4835169); way(r); rel(bw)[admin_level=8]; out geom;"
 - lu.json: Landnutzung aus osm2json.py
Ergänzt boundaries.geojson um die Nachbargemeinden und schreibt Flächen (Wohn-/Gewerbeinseln) je Dorf.
"""
import json, sys, math
from shapely.geometry import Polygon, MultiPolygon, Point
from shapely.ops import unary_union

KX, KY = 75560.0, 111320.0
P = lambda lat, lon: (lon * KX, lat * KY)
U = lambda x, y: (round(y / KY, 5), round(x / KX, 5))

# Kategorie der Wohnfläche + Texte (Lage, Beschreibung, Bezug zum Modell)
DORF = {
 'Natters': ('gehoben', 'Mittelgebirgsterrasse südwestlich von Innsbruck, oberhalb der Sillschlucht',
   'Früheres Bauerndorf, heute überwiegend Einfamilien‑ und kleine Mehrfamilienhäuser im Grünen. Die Stubaitalbahn und die Natterer Straße verbinden das Dorf mit der Stadt.',
   'Suburbane Wohninsel: Wohnen im Grünen, Arbeit, Schule und Einkauf großteils in Innsbruck. Die Zählstelle Natters zeigt den täglichen Pendelrhythmus.'),
 'Mutters': ('gehoben', 'Mittelgebirge südlich von Innsbruck, am Fuß der Mutterer Alm',
   'Wohndorf mit lockerer Bebauung und vielen Einfamilienhäusern. Über die Mutterer Straße und die Stubaitalbahn ist die Innenstadt in rund 20 Minuten erreichbar.',
   'Typischer Suburbanisierungsraum: Zuzug aus der Stadt, hohe Bodenpreise, wenig eigene Arbeitsplätze – Pendeln verbindet die Wohninsel mit der Stadt.'),
 'Aldrans': ('gehoben', 'Südöstliches Mittelgebirge, oberhalb von Amras',
   'Ruhiges Wohndorf auf der Mittelgebirgsterrasse, eng verflochten mit Innsbruck. Die Aldranser Straße führt über Schloss Ambras in die Stadt.',
   'Gehobenes suburbanes Wohnen am Stadtrand. Die Zählstelle Schloss Ambras misst den Verkehr von und nach Aldrans.'),
 'Lans': ('gehoben', 'Südöstliches Mittelgebirge, zwischen Igls und Sistrans',
   'Kleines Dorf mit Lanser See und Golfplatz in der Nähe, geprägt von Einfamilienhäusern und Freizeitnutzung.',
   'Exklusive Wohn‑ und Freizeitinsel im Grünen – ein Beispiel für die bevorzugten, gut erreichbaren Wohnlagen der Oberschicht am Stadtrand.'),
 'Patsch': ('gehoben', 'Mittelgebirge am Hang des Patscherkofels, oberhalb der Europabrücke',
   'Kleines Dorf über dem Wipptal, nahe der Brennerautobahn. Überwiegend Wohnen, kaum Arbeitsplätze im Ort.',
   'Suburbane Wohninsel; die Autobahn A13 trennt den Raum, bindet ihn aber zugleich an die Stadt an.'),
 'Ampass': ('gehoben', 'Östlich von Innsbruck, auf der Terrasse über der A12',
   'Dorf zwischen Innsbruck und Hall. Neue Wohngebiete sind in den letzten Jahrzehnten stark gewachsen.',
   'Wohnen im Umland mit schneller Autobahnanbindung – die Grenze zwischen Stadt und Land verschwimmt.'),
 'Schönberg im Stubaital': ('gehoben', 'Eingang des Stubaitals, an der Brennerautobahn',
   'Dorf am Talausgang des Stubaitals. Unterhalb liegt die Mautstelle Schönberg der A13 – laut Jahreswerten 2025 rund 37.000 Kfz pro Tag.',
   'Die Brennerautobahn wirkt als Barriere und zugleich als Verkehrsachse: Durchgangsverkehr und Pendeln treffen hier aufeinander.'),
 'Zirl': ('gemischt', 'Westlich von Innsbruck, am Fuß des Zirler Bergs',
   'Marktgemeinde mit eigenem Ortszentrum, Wohnbauten verschiedener Größe und Betrieben im Talboden.',
   'Teilweise eigenständiger Ort, aber über A12 und B171 eng mit Innsbruck verflochten – die Stadtregion wächst entlang der Verkehrsachsen.'),
 'Thaur': ('gemischt', 'Östlich von Rum, am Fuß des Karwendels',
   'Altes Haufendorf am Hang; im Talboden zur Autobahn hin Gewerbe‑ und Handelsflächen, die an jene von Rum anschließen.',
   'Zeigt die Trennung: Wohnen am Hang, Gewerbe‑ und Konsuminseln im Tal an der Autobahn.'),
 'Rum': None, 'Völs': None, 'Scharnitz': None,   # Rum/Völs: Flächen schon vorhanden; Scharnitz: Ort liegt weit im Karwendel
}
GEW = {'Zirl', 'Thaur', 'Ampass'}

def rings(ways):
    ways = [[(round(p['lon'], 6), round(p['lat'], 6)) for p in w] for w in ways]
    res = []
    while ways:
        r = ways.pop(0); ch = True
        while r[0] != r[-1] and ch:
            ch = False
            for i, w in enumerate(ways):
                if w[0] == r[-1]: r += w[1:]
                elif w[-1] == r[-1]: r += w[::-1][1:]
                elif w[-1] == r[0]: r = w[:-1] + r
                elif w[0] == r[0]: r = w[::-1][:-1] + r
                else: continue
                ways.pop(i); ch = True; break
        if r[0] == r[-1] and len(r) > 3: res.append(r)
    return res

nb = json.load(open(sys.argv[1], encoding='utf8'))['elements']
lu = json.load(open(sys.argv[2], encoding='utf8'))['elements']
bnd = json.load(open(sys.argv[3], encoding='utf8'))
have = {f['properties']['osm_id'] for f in bnd['features']}

def lu_polys(pred):
    out = []
    for el in lu:
        t = el.get('tags', {})
        if not pred(t): continue
        g = el['geometry']
        if len(g) < 4: continue
        try:
            pg = Polygon([P(p['lat'], p['lon']) for p in g]).buffer(0)
            if pg.area > 500: out.append(pg)
        except Exception: pass
    return out
RES = lu_polys(lambda t: t.get('landuse') == 'residential')
IND = lu_polys(lambda t: t.get('landuse') in ('industrial', 'commercial', 'retail'))

# bestehende (handgezeichnete) Flächen, wie im Browser geglättet -> neue Flächen dürfen sie nicht überlappen
def chaikin(r, it=4):
    for _ in range(it):
        o = []
        for k in range(len(r)):
            p, q = r[k], r[(k + 1) % len(r)]
            o += [(.75 * p[0] + .25 * q[0], .75 * p[1] + .25 * q[1]), (.25 * p[0] + .75 * q[0], .25 * p[1] + .75 * q[1])]
        r = o
    return r
import os
OLD = unary_union([Polygon([P(la, lo) for la, lo in chaikin(a['coords'])]).buffer(0)
                   for a in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'content.json'), encoding='utf8'))['areas']]).buffer(60)
areas = []
for e in nb:
    name = e['tags']['name']
    rs = rings([m['geometry'] for m in e['members'] if m['type'] == 'way' and m.get('role', 'outer') in ('outer', '') and 'geometry' in m])
    if e['id'] not in have:
        bnd['features'].append({'type': 'Feature', 'properties': {'name': name, 'kind': 'gemeinde', 'osm_id': e['id']},
            'geometry': {'type': 'MultiPolygon', 'coordinates': [[[[round(x, 5), round(y, 5)] for x, y in Polygon(r).simplify(0.00012).exterior.coords]] for r in rs]}})
    d = DORF.get(name)
    if not d: continue
    muni = unary_union([Polygon([P(la, lo) for lo, la in r]).buffer(0) for r in rs])
    def islands(polys, minA, keep):
        sel = [p for p in polys if muni.contains(p.representative_point())]
        if not sel: return []
        u = unary_union(sel).buffer(70).buffer(-45).simplify(18).intersection(muni.buffer(-15)).difference(OLD)
        parts = list(u.geoms) if hasattr(u, 'geoms') else [u]
        parts = sorted([p for p in parts if p.geom_type == 'Polygon' and p.area >= minA], key=lambda p: -p.area)[:keep]
        return parts
    for i, pg in enumerate(islands(RES, 60000, 2)):
        areas.append({'id': 'dorf_' + str(e['id']) + '_' + str(i), 'cat': d[0], 'name': name + ('' if i == 0 else ' (Ortsteil)'),
                      'lage': d[1], 'text': d[2], 'modell': d[3],
                      'coords': [list(U(x, y)) for x, y in list(pg.exterior.coords)[:-1]]})
    if name in GEW:
        for pg in islands(IND, 50000, 1):
            areas.append({'id': 'gew_' + str(e['id']), 'cat': 'gewerbe', 'name': 'Gewerbegebiet ' + name,
                'lage': 'Talboden von ' + name + ', nahe der Autobahn',
                'text': 'Betriebs‑, Lager‑ und Handelsflächen außerhalb des Ortskerns, ausgewiesen als Industrie‑ bzw. Gewerbegebiet.',
                'modell': 'Gewerbeinsel an der Autobahn: Betriebe suchen billigen Boden und gute Erreichbarkeit – abseits der Wohngebiete.',
                'coords': [list(U(x, y)) for x, y in list(pg.exterior.coords)[:-1]]})
    print(name, [a['cat'] + ':' + str(len(a['coords'])) for a in areas if a['name'].startswith(name) or a['name'].endswith(name)])

json.dump(bnd, open(sys.argv[3], 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
json.dump(areas, open(sys.argv[4], 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
print(len(bnd['features']), 'Grenzen,', len(areas), 'neue Flächen')

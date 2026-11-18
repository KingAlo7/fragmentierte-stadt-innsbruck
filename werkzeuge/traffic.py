"""Ordnet die Verkehrszählstellen (Land Tirol / ASFINAG) Straßenabschnitten aus OpenStreetMap zu.

Aufruf: python traffic.py road.json profiles.json traffic.json
 - road.json: Overpass-Export der Hauptstraßen (out geom)
 - profiles.json: mittlere Stundenwerte je Zählstelle und Richtung (aus den Stundendaten des Landes Tirol)
Jede Straße (Filter nach ref/Name) wird auf die nächstgelegene Zählstelle derselben Straße aufgeteilt.
"""
import json, sys, math

CENTER = (47.2672, 11.3955)
E_, W_, N_, S_ = (47.28, 11.52), (47.262, 11.30), (47.275, 11.395), (47.22, 11.39)

# id, Name, Straße, KFZ/24h (JDTV), LkwÄ/24h, Jahr, Filter(ref, Namen oder None), Anker (lat,lon), Radius m, Ziel Richtung 1
ST = [
 ('8851', 'Innsbruck-Völs', 'L 11 Völser Straße', 8719, 380, 2025, ('L11', None), (47.2555, 11.330), 1900, CENTER),
 ('8853', 'Innsbruck-Justizanstalt', 'L 11 Völser Straße', 12057, 516, 2025, ('L11', None), (47.2585, 11.356), 1500, CENTER),
 ('8882', 'Innsbruck-Innrain', 'L 11 Innrain', 12493, 728, 2025, ('L11', None), (47.2595, 11.380), 1100, CENTER),
 ('8852', 'Innsbruck-Götzens', 'L 12 Götzner Straße', 8483, 365, 2025, ('L12', None), (47.246, 11.335), 3000, CENTER),
 ('8881', 'Innsbruck-Technik', 'B 171 Kranebitter Allee', 16097, 676, 2024, ('B171', None), (47.2635, 11.346), 2600, CENTER),
 ('8157', 'Innsbruck-Haller Straße', 'B 171 Haller Straße', 17537, 642, 2025, ('B171', None), (47.2790, 11.425), 1700, E_),
 ('8155', 'Thaur', 'B 171 Tiroler Straße', 29699, 1501, 2025, ('B171', None), (47.2775, 11.468), 2400, E_),
 ('8883', 'Innsbruck-Egger-Lienz-Straße', 'B 174 Egger-Lienz-Straße', 31913, 1114, 2025, ('B174', None), (47.2575, 11.386), 1000, CENTER),
 ('8884', 'Innsbruck-Mitte', 'B 174 Olympiastraße', 25043, 944, 2025, ('B174', None), (47.2578, 11.405), 900, CENTER),
 ('8885', 'Innsbruck-Ost', 'B 174 Amraser-See-Straße', 40448, 2522, 2024, ('B174', None), (47.2620, 11.428), 1200, (47.258, 11.45)),
 ('8246', 'Rum', 'L 8 Rumer Straße', 6235, 264, 2025, ('L8', None), (47.2850, 11.443), 1700, N_),
 ('8213', 'Innsbruck-Vill', 'L 9 Igler Straße', 6101, 280, 2025, ('L9', {'Igler Straße', 'Resselstraße'}), (47.2440, 11.403), 2200, N_),
 ('8158', 'Innsbruck-Süd', 'B 182 Brennerstraße', 8412, 424, 2025, ('B182', None), (47.2440, 11.396), 2200, N_),
 ('8208', 'Innsbruck-Schloss Ambras', 'L 32 Aldranser Straße', 7071, 277, 2025, ('L32', None), (47.2545, 11.428), 1400, CENTER),
 ('8237', 'Natters', 'L 226 Natterer Straße', 4350, 145, 2025, ('L226', None), (47.2370, 11.378), 1100, N_),
 ('8238', 'Mutters', 'L 227 Mutterer Straße', 5540, 127, 2025, ('L227', None), (47.2320, 11.383), 1300, N_),
 # ASFINAG (Autobahnen): keine Stundendaten frei verfügbar -> Tagesgang aus Landeszählstellen geschätzt
 ('A557', 'A 12 Zählstelle Kematen', 'A 12 Inntal Autobahn (westlich Innsbruck)', 65640, 4821, 2025, ('A12', None), (47.262, 11.300), 6500, E_),
 ('A464', 'A 12 Zählstelle Hall-Mitte', 'A 12 Inntal Autobahn (östlich Innsbruck)', 61920, 10111, 2025, ('A12', None), (47.270, 11.470), 6500, E_),
 ('A183', 'A 13 Zählstelle Gärberbach', 'A 13 Brenner Autobahn', 49183, 8847, 2025, ('A13', {'Brenner Autobahn', 'Europabrücke', None}), (47.235, 11.385), 6000, S_),
 ('A521', 'A 13 Zählstelle Westast', 'A 13 Westast Innsbruck', 19883, 2239, 2025, ('A13', {'Westast Innsbruck'}), (47.245, 11.375), 4000, S_),
]

def dist(a, b):
    return math.hypot((a[0] - b[0]) * 111320, (a[1] - b[1]) * 75500)

def dp(pts, tol):
    if len(pts) < 3: return pts
    a, b = pts[0], pts[-1]
    ax, ay, bx, by = a[1] * 75500, a[0] * 111320, b[1] * 75500, b[0] * 111320
    L = math.hypot(bx - ax, by - ay) or 1e-9
    mi, md = 0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i][1] * 75500, pts[i][0] * 111320
        d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / L
        if d > md: mi, md = i, d
    if md <= tol: return [a, b]
    return dp(pts[:mi + 1], tol)[:-1] + dp(pts[mi:], tol)

roads = json.load(open(sys.argv[1], encoding='utf8'))['elements']
prof = json.load(open(sys.argv[2], encoding='utf8'))

def match(t, flt):
    ref, names = flt
    if t.get('ref', '').replace(' ', '').split(';')[0] != ref: return False
    if t.get('highway', '').endswith('_link'): return False
    return names is None or t.get('name') in names

# Mittlerer Tagesgang (normiert) für Autobahnen aus allen Landeszählstellen
def norm(v):
    s = sum(v) or 1; return [x / s for x in v]
avg = {'werktag': [0] * 24, 'wochenende': [0] * 24}
for p in prof.values():
    for d in p['dirs']:
        for k in avg:
            n = norm(d[k]); avg[k] = [a + b for a, b in zip(avg[k], n)]
for k in avg: avg[k] = norm(avg[k])

out = []
for s in ST:
    sid, name, road, jdtv, lkw, year, flt, anchor, R, target = s
    rivals = [r for r in ST if r[6][0] == flt[0] and r is not s]
    paths = []
    for el in roads:
        t = el['tags']
        if not match(t, flt): continue
        g = [(p['lat'], p['lon']) for p in el['geometry']]
        mid = g[len(g) // 2]
        dm = dist(mid, anchor)
        if dm > R: continue
        if any(dist(mid, r[7]) < dm and match(t, r[6]) for r in rivals): continue
        # Richtung 1 = vorwärts entlang der Geometrie
        fwd = dist(g[-1], target) < dist(g[0], target)
        if not fwd: g = g[::-1]
        ow = t.get('oneway') in ('yes', '1', 'true') or t.get('highway') == 'motorway'
        dirs = [0, 1]
        if ow:
            dirs = [0] if fwd else [1]
        g = dp(g, 4)
        paths.append({'c': [[round(a, 5), round(b, 5)] for a, b in g], 'd': dirs})
    if not paths:
        print('KEIN ABSCHNITT', sid, name); continue
    # Stationsposition: nächster Punkt auf dem Korridor zum Anker
    best = min((pt for p in paths for pt in p['c']), key=lambda pt: dist(pt, anchor))
    if sid in prof:
        dirs = [{'label': d['dir'], 'werktag': d['werktag'], 'wochenende': d['wochenende']} for d in prof[sid]['dirs']]
        est = False
    else:
        half = jdtv / 2
        dirs = [{'label': lbl, 'werktag': [round(x * half * 1.04, 1) for x in avg['werktag']],
                 'wochenende': [round(x * half * 0.9, 1) for x in avg['wochenende']]} for lbl in ('Richtung 1', 'Richtung 2')]
        est = True
    out.append({'id': sid, 'name': name, 'road': road, 'jdtv': jdtv, 'lkw': lkw, 'year': year,
                'pos': best, 'paths': paths, 'dirs': dirs, 'est': est, 'asfinag': sid.startswith('A')})
    print(sid, name, len(paths), 'Abschnitte', 'geschätzt' if est else 'gemessen')
json.dump(out, open(sys.argv[3], 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))

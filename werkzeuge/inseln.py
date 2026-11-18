"""Namen, Lage und Kennzahlen für die Inseln aus bloecke.py.

Aufruf: python inseln.py daten/bloecke.geojson lu.json poi.json content.json daten/flaechen.json
Schreibt daten/flaechen.json (Karte) und daten/flaechen_wohnen.json (Wohnen im Detail).

Name = Bezeichnung + Ort (+ Bauform) + (Grenzstraßen)
- Bezeichnung: Eigenname aus OSM, wenn ein benanntes Gelände die Insel prägt (Gewerbegebiet, Einkaufszentrum, Schule,
  Park, Sportanlage), sonst die genaue Nutzung (Wohngebiet, Sportanlage, Park/Grünanlage ...).
- Ort: alle OSM-Ortsteile in der Insel (höchstens drei), sonst der nächste Ortsteil bis 300 m, sonst Stadtteil bzw. Gemeinde.
- Bauform (Wohnen): nach Geschoßfläche der amtlichen Gebäude (tiris, Höhe aus Laserscan).
- Grenzstraßen: die bis zu drei benannten Straßen, die die Insel am längsten begleiten (OSM).
"""
import json, sys, math, base64
from collections import Counter
import numpy as np
from matplotlib.path import Path
from scipy.ndimage import zoom
from shapely.geometry import shape, Point, Polygon, LineString
from shapely.strtree import STRtree

fb, flu, fpoi, fcont, fout = sys.argv[1:6]
KX, KY = 111320 * math.cos(math.radians(47.26)), 111320.0
ha_of = lambda g: g.area * KX * KY / 1e4

B = json.load(open(fb, encoding='utf8'))['features']
lu = json.load(open(flu, encoding='utf8'))['elements']
poi = json.load(open(fpoi, encoding='utf8'))['elements']
content = json.load(open(fcont, encoding='utf8'))
ORTE = [o for o in json.load(open('daten/orte.json', encoding='utf8')) if 3 <= o['rank'] <= 6]
OPT = [Point(o['lon'], o['lat']) for o in ORTE]
BND = json.load(open('../boundaries.geojson', encoding='utf8'))['features']
STT = [(shape(f['geometry']).buffer(0), 'Innenstadt' if f['properties']['name'] == 'Innsbruck' else f['properties']['name'])
       for f in BND if f['properties']['kind'] == 'stadtteil']

# --- Straßen (OSM, aus dem Verkehrsnetz) ---
SL, SN, SK = [], [], []
for e in json.load(open('daten/netz.json', encoding='utf8'))['edges']:
    if not e['n']: continue
    g = e['g']; pts = []; la = lo = 0
    for i in range(0, len(g), 2): la += g[i]; lo += g[i + 1]; pts.append((lo / 1e5, la / 1e5))
    if len(pts) > 1: SL.append(LineString(pts)); SN.append(e['n']); SK.append(e['k'])
STREE = STRtree(SL)
def strassen(p):
    ring = p.exterior.buffer(30 / KY)
    c, kk = Counter(), {}
    for i in STREE.query(ring):
        if SL[i].intersects(ring):
            c[SN[i]] += SL[i].intersection(ring).length * KX; kk[SN[i]] = max(kk.get(SN[i], 0), SK[i])
    import re
    L = [n for n, v in c.items() if v >= 60]
    if sum(1 for n in L if not re.fullmatch(r'[A-Z]\d+[a-z]?', n)) >= 2: L = [n for n in L if not re.fullmatch(r'[A-Z]\d+[a-z]?', n)]
    L.sort(key=lambda n: (-(kk[n] >= 3), -c[n]))
    return L[:3]

# --- benannte Gelände (OSM) ---
PROP = []   # (Polygon, Name, Kategorie)
def propcat(t):
    if t.get('landuse') in ('industrial', 'commercial'): return 'gewerbe'
    if t.get('landuse') == 'retail' or t.get('shop') in ('mall', 'department_store'): return 'konsum'
    if t.get('amenity') in ('school', 'university', 'college') or t.get('landuse') == 'education': return 'bildung'
    if t.get('leisure') in ('park', 'sports_centre', 'stadium', 'golf_course', 'swimming_pool', 'water_park', 'garden', 'pitch') \
       or t.get('tourism') in ('zoo', 'camp_site') or t.get('landuse') == 'recreation_ground': return 'erholung'
    return None
for el in lu:
    t = el.get('tags', {}); n = t.get('name'); k = propcat(t)
    if not n or not k: continue
    try: pg = Polygon([(q['lon'], q['lat']) for q in el['geometry']]).buffer(0)
    except Exception: continue
    if ha_of(pg) >= 0.2: PROP.append((pg, n, k))
PTREE = STRtree([p for p, _, _ in PROP])
MALLS = []
for el in poi:
    t = el.get('tags', {}); c = el.get('center') or el
    if t.get('shop') in ('mall', 'department_store') and t.get('name') and 'lat' in c:
        MALLS.append((Point(c['lon'], c['lat']), t['name']))
def eigenname(p, cat):
    names = []
    if cat == 'gewerbe':   # Ortsteile wie „Gewerbegebiet Roßau“
        names += [ORTE[i]['name'] for i, q in enumerate(OPT) if p.buffer(0.0005).contains(q) and 'gewerbe' in ORTE[i]['name'].lower()]
    if cat == 'konsum':
        names += [n if any(w in n.lower() for w in ('center', 'zentrum', 'galerie', 'kaufhaus', 'ekz', 'markthalle', 'shopping'))
                  else 'Einkaufszentrum ' + n for q, n in MALLS if p.contains(q)]
    best = []
    for i in PTREE.query(p):
        pg, n, k = PROP[i]
        if k != cat or not pg.intersects(p): continue
        a = pg.intersection(p).area
        if a >= 0.5 * p.area: best.append((a, n))   # nur Gelände, das mindestens die halbe Insel ausmacht
    best.sort(reverse=True)
    for _, n in best:
        if n not in names: names.append(n)
    out = []
    for n in names:
        if n not in out: out.append(n)
    return out[:2]

def ort(p, gem):
    inside = [(ORTE[i]['rank'], ORTE[i]['name']) for i, q in enumerate(OPT) if p.buffer(30 / KY).contains(q)
              and 'gewerbe' not in ORTE[i]['name'].lower() and ORTE[i]['name'] != gem]
    inside = [n for _, n in sorted(set(inside))]
    st = sorted(((s.intersection(p).area, n) for s, n in STT if gem == 'Innsbruck' and s.intersects(p)), reverse=True)
    stn = [n for a, n in st if a > 0.1 * p.area] or [n for _, n in st[:1]]
    if not inside:
        c = p.representative_point()
        near = sorted((c.distance(q) * KY, ORTE[i]['name']) for i, q in enumerate(OPT)
                      if ORTE[i]['name'] != gem and 'gewerbe' not in ORTE[i]['name'].lower())
        if near and near[0][0] <= 300: inside = [near[0][1]]
    if gem == 'Innsbruck':
        if len(inside) >= 2 and stn and stn[0] not in inside: label = f'{stn[0]}: ' + ', '.join(inside[:3])
        elif inside: label = ', '.join(inside[:3])
        else: label = stn[0] if stn else 'Innsbruck'
    else:
        label = gem + (', ' + ', '.join(inside[:3]) if inside else '')
    return label, inside, stn

# --- Heatmap-Dichten für die Balken ---
heat = json.load(open('daten/heat.json', encoding='utf8'))
(S, W), (N, E) = heat['bounds']; hh, ww = heat['h'], heat['w']
MAINK = ['konsum', 'gewerbe', 'wohnen', 'bildung', 'erholung']
HV = {k: np.frombuffer(base64.b64decode(heat['cats'][k]), np.uint8).reshape(hh, ww) / 255.0 for k in MAINK}
def mix(p):
    x0, y0, x1, y1 = p.bounds
    c0, c1 = max(0, int((x0 - W) / (E - W) * ww)), min(ww, int((x1 - W) / (E - W) * ww) + 1)
    r0, r1 = max(0, int((N - y1) / (N - S) * hh)), min(hh, int((N - y0) / (N - S) * hh) + 1)
    if r0 >= r1 or c0 >= c1: return {}      # außerhalb des Heatmap-Rasters (z. B. Scharnitz)
    rr, cc = np.mgrid[r0:r1, c0:c1]
    pts = np.column_stack([(W + (cc + .5) / ww * (E - W)).ravel(), (N - (rr + .5) / hh * (N - S)).ravel()])
    m = Path(np.array(p.exterior.coords)).contains_points(pts).reshape(rr.shape)
    if not m.any():
        c = p.representative_point(); r = min(hh - 1, int((N - c.y) / (N - S) * hh)); q = min(ww - 1, int((c.x - W) / (E - W) * ww))
        return {k: round(float(HV[k][r, q]), 3) for k in MAINK}
    return {k: round(float(HV[k][rr, cc][m].mean()), 3) for k in MAINK}

# --- POIs (OSM) für Kennzahlen ---
PP, PT = [], []
for el in poi:
    t = el.get('tags', {}); c = el.get('center') or el
    if 'lat' not in c: continue
    PP.append(Point(c['lon'], c['lat']))
    PT.append('shop' if 'shop' in t else 'gastro' if t.get('amenity') in ('restaurant', 'cafe', 'fast_food') else
              'bildung' if t.get('amenity') in ('university', 'college', 'school', 'research_institute', 'kindergarten', 'library') else
              'betrieb' if ('craft' in t or 'office' in t) else 'sonst')
PTR = STRtree(PP)

BEZ = {'wohnen': 'Wohngebiet', 'konsum': 'Geschäftsgebiet', 'gewerbe': 'Gewerbegebiet', 'bildung': 'Bildungsstandort',
       'gehoben': 'Einfamilienhausgebiet', 'gemischt': 'Mehrfamilienhausgebiet', 'gross': 'Großwohnanlage'}
ERH = {'Anlagen: Grünanlagen': 'Park/Grünanlage', 'Sport und Erholung: Sportanlage': 'Sportanlage', 'Sport und Erholung: Golfplatz': 'Golfplatz',
       'Anlagen: Camping': 'Campingplatz', 'Anlagen: Erholung, Freizeit': 'Freizeitanlage'}
BFN = {'gehoben': 'Einfamilienhäuser', 'gemischt': 'Mehrfamilienhäuser', 'gross': 'Großwohnanlagen'}
BFL = {'gehoben': 'Ein- und Zweifamilienhäuser', 'gemischt': 'Mehrfamilienhäuser', 'gross': 'Großwohnbauten (ab 7 Geschoßen oder sehr große Grundfläche)'}
MODELL = {
 'konsum': 'Konsum verlagert sich an gut erreichbare Standorte; Einkaufsinseln entstehen neben der Altstadt auch am Stadtrand.',
 'gewerbe': 'Produktion und Lager suchen billigen Boden und Autobahnnähe – sie bilden eigene, vom Wohnen getrennte Inseln.',
 'wohnen': 'Wohninsel: Wohnen ist räumlich von Arbeit, Konsum und Bildung getrennt – dazwischen liegt der tägliche Pendelverkehr.',
 'bildung': 'Bildung und Forschung konzentrieren sich in spezialisierten Campus-Inseln.',
 'erholung': 'Freizeitinseln: Sport, Baden und Erholung sind in eigenen, spezialisierten Anlagen gebündelt, die oft gezielt angefahren werden.',
 'gehoben': 'Suburbane Wohninsel: Wohnen im Grünen am Stadtrand oder im Umland, Arbeit und Versorgung anderswo – Pendelverkehr.',
 'gemischt': 'Rest der kompakten, gemischt genutzten Stadt; hier überlagern sich noch Wohnen, Arbeiten und Versorgen.',
 'gross': 'Geplante Wohnsiedlungen des sozialen Wohnbaus bilden eigene, oft abgegrenzte Wohninseln.',
 'barriere': 'Barriere: Infrastrukturflächen trennen die Inseln der Stadt voneinander.'}
curated = [(Polygon([(lo, la) for la, lo in a['coords']]).buffer(0), a) for a in content['areas']]

def pct(x): return f'{round(x * 100)} %'
def describe(feats, handcats, pre):
    out, used = [], set()
    feats = sorted(feats, key=lambda f: -shape(f['geometry']).area)
    for idx, f in enumerate(feats):
        pr = f['properties']; k = pr['cat']; gem = pr['gem']
        p = shape(f['geometry']).buffer(0)
        if p.geom_type != 'Polygon': p = max(getattr(p, 'geoms', [p]), key=lambda x: x.area)
        st = strassen(p); label, ots, stn = ort(p, gem)
        bf = pr.get('bf') or {}
        dom = max(bf, key=bf.get) if bf else None
        pc = Counter(PT[j] for j in PTR.query(p, predicate='contains'))
        if k == 'barriere':
            name, text = 'Flughafen Innsbruck', 'Flughafengelände mit Rollfeld (amtliche Landnutzung „Flugverkehr“, Rollfeld aus OSM): eine große, nicht durchquerbare Fläche zwischen Stadt und Inn.'
        else:
            own = eigenname(p, k) if k in ('konsum', 'gewerbe', 'bildung', 'erholung') else []
            malls = [n for q, n in MALLS if p.contains(q)]
            if k == 'konsum' and ha_of(p) >= 8: own = []   # großes Geschäftsgebiet: nach dem Ort benennen, Kaufhäuser im Text
            bez = ERH.get(pr.get('klasse'), 'Erholungs- und Freizeitfläche') if k == 'erholung' else BEZ[k]
            if own:
                name = ' / '.join(own)
                if k == 'gewerbe' and 'gewerbe' not in name.lower() and 'industrie' not in name.lower(): name = 'Gewerbegebiet ' + name
            else:
                name = f'{bez} {label}'
            if k == 'wohnen' and dom:
                name += ' – ' + (BFN[dom] if bf[dom] >= 0.55 else 'gemischte Bebauung')
            # Texte
            if k in BFN or k == 'wohnen':
                anteile = ', '.join(f'{pct(v)} {BFL[q]}' for q, v in sorted(bf.items(), key=lambda kv: -kv[1]) if v >= 0.05)
                text = (f'Wohngebiet laut amtlicher Realnutzung ({pr.get("klasse")}). ' if k == 'wohnen' else
                        f'Teil eines Wohngebiets, in dem {BFL[k]} überwiegen. ') + \
                       (f'Bauform nach Geschoßfläche der Gebäude: {anteile}.' if anteile else '')
            elif k == 'gewerbe':
                text = 'Industrie- und Gewerbefläche laut amtlicher Realnutzung (Land Tirol).'
            elif k == 'konsum':
                text = ('Handelsfläche laut amtlicher Realnutzung.' if 'Handel' in pr.get('klasse', '') else
                        'Gemischt genutzte Blöcke mit Kern- bzw. Handelswidmung und hoher Geschäftsdichte.') + \
                       (f' {pc["shop"] + pc["gastro"]} Geschäfte und Lokale (OSM).' if pc['shop'] + pc['gastro'] else '') +                        (' Einkaufszentren und Kaufhäuser: ' + ', '.join(dict.fromkeys(malls)) + '.' if malls else '')
            elif k == 'bildung':
                text = 'Schul- bzw. Hochschulgelände: überwiegend als Bildungsfläche gewidmet oder in OSM als Schul-/Hochschulgelände erfasst.'
            else:
                text = f'{pr.get("klasse") or "Erholungsfläche"} laut amtlicher Realnutzung (Land Tirol).'
        if st: name += ' (' + ' – '.join(st) + ')'
        # handgeschriebener Text derselben Kategorie
        cur = None
        for cp, a in curated:
            if a['cat'] == k and k in handcats and a['id'] not in used and cp.intersects(p):
                ov = cp.intersection(p).area
                if ov > 0.3 * min(cp.area, p.area) and (cur is None or ov > cur[0]): cur = (ov, a)
        if cur: used.add(cur[1]['id']); text = cur[1]['text'] + ' ' + text
        lage = ' · '.join(x for x in [gem, ('Stadtteil ' + ' / '.join(stn)) if stn else '',
                                       ('Ortsteile: ' + ', '.join(ots)) if ots else ''] if x)
        geb = {'haus': pr['ngeb'].get('gehoben', 0), 'wohn': pr['ngeb'].get('gemischt', 0), 'hoch': pr['ngeb'].get('gross', 0)} \
              if (k == 'wohnen' or k in BFN) else {}
        rings = [[[round(y, 5), round(x, 5)] for x, y in p.exterior.coords[:-1]]] + \
                [[[round(y, 5), round(x, 5)] for x, y in r.coords[:-1]] for r in p.interiors if ha_of(Polygon(r)) > 0.15]
        out.append({'id': f'{pre}{idx}', 'cat': k, 'name': name, 'lage': lage, 'text': text, 'modell': MODELL.get(k, ''),
                    'ha': round(ha_of(p), 1), 'mix': mix(p) if k != 'barriere' else {}, 'bf': bf if (k == 'wohnen' or k in BFN) else {},
                    'geb': geb, 'poi': dict(pc), 'strassen': st, 'rings': rings, 'hand': bool(cur)})
    return out

main = describe([f for f in B if f['properties']['ebene'] == 'haupt'], ('konsum', 'gewerbe', 'bildung', 'barriere'), 'f')
sub = describe([f for f in B if f['properties']['ebene'] == 'wohnen'], ('gehoben', 'gemischt', 'gross'), 'w')
json.dump(main, open(fout, 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
json.dump(sub, open(fout.replace('.json', '_wohnen.json'), 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
print(len(main), 'Inseln', Counter(o['cat'] for o in main), '|', len(sub), 'Wohn-Teilflächen | mit Handtext', sum(o['hand'] for o in main + sub))
for o in main[:25]: print(f"  {o['ha']:6.1f} ha  {o['name']}")

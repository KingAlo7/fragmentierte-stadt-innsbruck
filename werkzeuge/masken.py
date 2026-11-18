"""Leitet die Flächen ("Masken") der fragmentierten Stadt aus den Heatmap-Rastern ab.

Aufruf: python masken.py daten/heat.json bld.json poi.json lu.json content.json daten/flaechen.json
Schreibt zusätzlich daten/flaechen_wohnen.json: die Wohnflächen, unterteilt nach Bauform (Tab „Wohnen im Detail“).

Verfahren
1. Heatmap-Raster (eine Dichte je Kategorie, 0..1) auf 37,5 m verfeinern.
2. Je Zelle gewinnt die stärkste Kategorie, sofern sie über der Schwelle T liegt (sonst "keine").
   Die Grenzen werden als Linie gleicher Stärke zweier Kategorien gezogen (glatt, lückenlos, ohne Überlappung).
3. Kleine Splitter (< MIN_HA) entfallen; der Flughafen kommt als Barriere-Fläche aus OSM dazu.
4. Für jede Fläche: Name (OSM-Ortsteil/Flurname), Zusammensetzung, Gebäude- und Geschäftszahlen;
   handgeschriebene Texte aus content.json werden übernommen, wenn eine Fläche derselben Kategorie überlappt.
"""
import json, sys, math, base64
import numpy as np
from scipy.ndimage import zoom, gaussian_filter
import contourpy
from shapely.geometry import Polygon, Point, MultiPolygon, shape
from shapely.ops import unary_union
from shapely.strtree import STRtree

T = 0.13          # Mindeststärke, damit eine Fläche entsteht
MIN_HA = 4.0      # kleinere Splitter entfallen
UP = 2            # Verfeinerung 75 m -> 37,5 m
SIG = 1.6         # Glättung der Grenzen (in feinen Zellen)
# Gewichte gleichen aus, dass Wohnkategorien flächig, Konsum/Bildung punktuell auftreten
WGT = {'konsum': 1.25, 'gewerbe': 1.1, 'wohnen': 0.9, 'bildung': 1.25, 'erholung': 1.0,
       'gehoben': 0.85, 'gemischt': 1.0, 'gross': 1.15}
MAIN = ['konsum', 'gewerbe', 'wohnen', 'bildung', 'erholung']   # Standardansicht: Wohnen als eine Kategorie
SUB = ['gehoben', 'gemischt', 'gross']                          # Unterteilung des Wohnens nach Bauform
MIN_HA_SUB = 1.5

heat = json.load(open(sys.argv[1]))
bld, poi, lu = (json.load(open(p, encoding='utf8'))['elements'] for p in sys.argv[2:5])
content = json.load(open(sys.argv[5], encoding='utf8'))
(S, W), (N, E) = heat['bounds']
h, w = heat['h'], heat['w']
VR = {k: zoom(np.frombuffer(base64.b64decode(heat['cats'][k]), np.uint8).reshape(h, w) / 255.0 * WGT[k], UP, order=1) for k in MAIN + SUB}
K = MAIN
V = np.stack([VR[k] for k in K])
H2, W2 = V.shape[1:]
KX, KY = 111320 * math.cos(math.radians((S + N) / 2)), 111320.0
cell_m2 = ((N - S) / H2 * KY) * ((E - W) / W2 * KX)

lab = np.where(V.max(0) >= T, V.argmax(0), -1)
# weiche Zugehörigkeit je Kategorie (+ "keine"), dann Grenzen = Gleichstand
M = np.stack([gaussian_filter((lab == i).astype(float), SIG) for i in range(-1, len(K))])

def to_ll(x, y):   # Rasterkoordinate (Spalte x, Zeile y) -> lat, lon
    return N - (y + .5) / H2 * (N - S), W + (x + .5) / W2 * (E - W)

def polys_for(i, M=M):
    others = np.delete(M, i + 1, axis=0).max(0)
    f = M[i + 1] - others
    f = np.pad(f, 1, constant_values=-1)
    gen = contourpy.contour_generator(z=f, fill_type=contourpy.FillType.OuterOffset)
    pts, offs = gen.filled(0, 10)
    out = []
    for P_, O in zip(pts, offs):
        rings = [P_[O[j]:O[j + 1]] for j in range(len(O) - 1)]
        rr = [[(lo, la) for la, lo in (to_ll(x - 1, y - 1) for x, y in r)] for r in rings]
        try:
            pg = Polygon(rr[0], rr[1:]).buffer(0)
        except Exception:
            continue
        out.append(pg)
    return out

# Flughafen (OSM aeroway=aerodrome) als Barriere-Fläche
airport = unary_union([Polygon([(p['lon'], p['lat']) for p in el['geometry']]).buffer(0)
                       for el in lu if el['tags'].get('aeroway') == 'aerodrome' and len(el['geometry']) > 3])

def area_ha(pg):
    c = pg.centroid
    return pg.area * KX * KY / 1e4

# Gebäude/POIs für Kennzahlen
HOUSE = {'house', 'detached', 'semidetached_house', 'villa', 'bungalow', 'terrace', 'farm'}
APT = {'apartments', 'residential', 'dormitory'}
IND = {'industrial', 'warehouse', 'manufacture', 'factory', 'commercial', 'office', 'retail', 'supermarket'}
bpts, btyp = [], []
for el in bld:
    g = el['geometry']
    la = sum(p['lat'] for p in g) / len(g); lo = sum(p['lon'] for p in g) / len(g)
    b = el['tags'].get('building', 'yes')
    try: lev = float(str(el['tags'].get('building:levels', '0')).split(';')[0])
    except ValueError: lev = 0
    bpts.append(Point(lo, la)); btyp.append('haus' if b in HOUSE else 'wohn' if b in APT else 'betrieb' if b in IND else 'hoch' if lev >= 7 else 'sonst')
    if lev >= 7: btyp[-1] = 'hoch'
btree = STRtree(bpts)
ppts, ptyp = [], []
for el in poi:
    t = el['tags']; c = el.get('center') or el
    if 'lat' not in c: continue
    ppts.append(Point(c['lon'], c['lat']))
    ptyp.append('shop' if 'shop' in t else 'gastro' if t.get('amenity') in ('restaurant', 'cafe', 'fast_food') else
                'bildung' if t.get('amenity') in ('university', 'college', 'school', 'research_institute', 'kindergarten', 'library') else
                'betrieb' if ('craft' in t or 'office' in t) else 'sonst')
ptree = STRtree(ppts)

# Ortsnamen: benannte Landnutzungsflächen und Ortsteile (place=*) aus OSM
named = []
for el in lu:
    n = el['tags'].get('name')
    if n and len(el['geometry']) > 3:
        try: named.append((Polygon([(p['lon'], p['lat']) for p in el['geometry']]).buffer(0), n, el['tags']))
        except Exception: pass
places = [(Point(el['lon'], el['lat']), el['tags']['name'], el['tags']['place']) for el in poi if False]

curated = [(Polygon([(lo, la) for la, lo in a['coords']]).buffer(0), a) for a in content['areas']]

CATL = {'konsum': 'Konsuminsel', 'gewerbe': 'Gewerbe & Produktion', 'gehoben': 'Suburbanes Wohnen',
        'gemischt': 'Wohnen gemischt', 'gross': 'Großwohnanlagen', 'bildung': 'Bildungs- & Wissensinsel',
        'wohnen': 'Wohnen', 'erholung': 'Erholung & Freizeit'}
SUBTXT = {'gehoben': 'Überwiegend Ein- und Zweifamilienhäuser (locker bebaut).',
          'gemischt': 'Überwiegend mittelgroße Mehrfamilienhäuser, oft mit Läden und Betrieben im Erdgeschoß.',
          'gross': 'Überwiegend große Wohnbauten: Wohnblöcke und -anlagen mit vielen Geschoßen.'}
GENERIC = {
 'konsum': 'Hier ballen sich Geschäfte, Gastronomie und Dienstleistungen stärker als in der Umgebung.',
 'gewerbe': 'Betriebs-, Lager- und Bürogebäude sowie ausgewiesene Industrie- und Gewerbeflächen prägen diesen Bereich.',
 'gehoben': 'Locker bebautes Wohngebiet mit überwiegend Ein- und Zweifamilienhäusern.',
 'gemischt': 'Dicht bebautes Wohngebiet mit mittelgroßen Mehrfamilienhäusern, oft gemischt mit Läden und Betrieben im Erdgeschoß.',
 'gross': 'Wohngebiet mit großen Wohnbauten: Wohnblöcke und -anlagen mit vielen Geschoßen.',
 'bildung': 'Schul-, Hochschul- oder Forschungsstandort mit großen Bildungsgebäuden.',
 'wohnen': 'Wohngebiet.',
 'erholung': 'Parks, Grünanlagen, Sport- und Spielplätze, Bäder oder Kleingärten prägen diesen Bereich (amtliche Widmung und OSM).'}
MODELL = {
 'konsum': 'Konsum verlagert sich an gut erreichbare Standorte; Einkaufsinseln entstehen neben der Altstadt auch am Stadtrand.',
 'gewerbe': 'Produktion und Lager suchen billigen Boden und Autobahnnähe – sie bilden eigene, vom Wohnen getrennte Inseln.',
 'gehoben': 'Suburbane Wohninsel: Wohnen im Grünen am Stadtrand oder im Umland, Arbeit und Versorgung anderswo – Pendelverkehr.',
 'gemischt': 'Rest der kompakten, gemischt genutzten Stadt; hier überlagern sich noch Wohnen, Arbeiten und Versorgen.',
 'gross': 'Geplante Wohnsiedlungen des sozialen Wohnbaus bilden eigene, oft abgegrenzte Wohninseln.',
 'bildung': 'Bildung und Forschung konzentrieren sich in spezialisierten Campus-Inseln.',
 'wohnen': 'Wohninsel: Wohnen ist räumlich von Arbeit, Konsum und Bildung getrennt – dazwischen liegt der tägliche Pendelverkehr. Welche Bauform überwiegt, zeigt der Tab „Wohnen im Detail“.',
 'erholung': 'Freizeitinseln: Sport, Baden und Erholung sind in eigenen, spezialisierten Anlagen gebündelt, die oft gezielt angefahren werden.'}

ORTE = json.load(open('daten/orte.json', encoding='utf8'))
LUOK = {'konsum': ('retail', 'commercial'), 'gewerbe': ('industrial', 'commercial'), 'bildung': ('education',)}
LEISOK = ('park', 'sports_centre', 'stadium', 'golf_course', 'water_park', 'swimming_pool', 'zoo', 'theme_park')
def place_name(pg, cat):
    best = None
    c = pg.centroid
    for npg, n, t in named:
        okt = (t.get('landuse') in LUOK.get(cat, ()) and any(w in n.lower() for w in ('gewerbe', 'industrie', 'einkauf', 'zentrum', 'park', 'center')))               or (cat == 'bildung' and t.get('amenity') in ('university', 'college')) \
               or (cat == 'erholung' and (t.get('leisure') in LEISOK or t.get('tourism') in LEISOK or t.get('landuse') == 'recreation_ground'))
        if not okt or not npg.intersects(pg): continue
        a = npg.intersection(pg).area
        if a > 0.25 * npg.area and (best is None or a > best[0]): best = (a, n)
    if best: return best[1]
    # Ortsteil im Inneren bevorzugen (Ortsteile vor Gemeindenamen), sonst nächster Ort < ~600 m
    cand = []
    for o in ORTE:
        if o['rank'] > 6: continue
        pt = Point(o['lon'], o['lat']); d = c.distance(pt)
        ins = pg.contains(pt)
        if ins or (d < 0.006 and pg.buffer(0.002).contains(pt)):
            pri = o['rank'] if o['rank'] >= 3 else o['rank'] + 4   # suburb/quarter/neighbourhood vor city/village
            cand.append((0 if ins else 1, pri, d, o['name']))
    if not cand: return None
    cand.sort()
    return cand[0][3]

GEMS = [shape(f['geometry']).buffer(0) for f in json.load(open('../boundaries.geojson', encoding='utf8'))['features']
        if f['properties']['kind'] == 'gemeinde']
STUDY = unary_union(GEMS)
feats = []
for i, k in enumerate(K):
    for pg in polys_for(i):
        if pg.is_empty: continue
        pg = pg.intersection(STUDY)
        if not airport.is_empty: pg = pg.difference(airport)
        # an Gemeindegrenzen teilen, damit jede Fläche eindeutig einer Gemeinde gehört
        parts = []
        for g in GEMS:
            q = pg.intersection(g)
            parts += list(q.geoms) if hasattr(q, 'geoms') else [q]
        for p in parts:
            if p.geom_type != 'Polygon' or area_ha(p) < MIN_HA: continue
            feats.append((k, p.simplify(0.00012)))
if not airport.is_empty:
    for p in (list(airport.geoms) if hasattr(airport, 'geoms') else [airport]):
        if area_ha(p) > 20: feats.append(('barriere', p.simplify(0.0001)))

# --- Unterteilung des Wohnens: innerhalb jeder Wohnfläche gewinnt die stärkste Bauform ---
VS = np.stack([VR[k] for k in SUB])
lab2 = np.where(VS.sum(0) > 0.01, VS.argmax(0), -1)
M2 = np.stack([gaussian_filter((lab2 == i).astype(float), SIG) for i in range(-1, len(SUB))])
subpolys = {k: unary_union(polys_for(i, M2)) for i, k in enumerate(SUB)}
feats_sub = []
for k0, p0 in feats:
    if k0 != 'wohnen': continue
    for k, sp in subpolys.items():
        q = p0.intersection(sp)
        for p in (list(q.geoms) if hasattr(q, 'geoms') else [q]):
            if p.geom_type == 'Polygon' and area_ha(p) >= MIN_HA_SUB: feats_sub.append((k, p.simplify(0.0001)))

# Gemeinde/Stadtteil zur Lagebeschreibung
B = json.load(open(sys.argv[6].replace('werkzeuge/daten/flaechen.json', 'boundaries.geojson') if False else '../boundaries.geojson', encoding='utf8'))
regions = [(shape(f['geometry']).buffer(0), f['properties']['name'], f['properties']['kind']) for f in B['features']]
def lage(p):
    c = p.representative_point()
    st = [n for g, n, kd in regions if kd == 'stadtteil' and g.contains(c)]
    gm = [n for g, n, kd in regions if kd == 'gemeinde' and g.contains(c)]
    st = ['Innenstadt' if s == 'Innsbruck' else s for s in st]
    return ', '.join(st + gm) or 'Umland'

def describe(feats, mixk, handcats, pre):
  out = []
  USED = set()
  feats.sort(key=lambda kp: -kp[1].area)
  for idx, (k, p) in enumerate(feats):
      bi = btree.query(p, predicate='contains'); pi = ptree.query(p, predicate='contains')
      bc = {}; [bc.__setitem__(btyp[j], bc.get(btyp[j], 0) + 1) for j in bi]
      pc = {}; [pc.__setitem__(ptyp[j], pc.get(ptyp[j], 0) + 1) for j in pi]
      # mittlere Stärke aller Kategorien in der Fläche
      mix = {}
      if k != 'barriere':
          x0, y0, x1, y1 = p.bounds
          c0 = int((x0 - W) / (E - W) * W2); c1 = int((x1 - W) / (E - W) * W2) + 1
          r0 = int((N - y1) / (N - S) * H2); r1 = int((N - y0) / (N - S) * H2) + 1
          rr, cc = np.mgrid[max(r0, 0):min(r1, H2), max(c0, 0):min(c1, W2)]
          lat = N - (rr + .5) / H2 * (N - S); lon = W + (cc + .5) / W2 * (E - W)
          inside = np.array([p.contains(Point(a, b)) for a, b in zip(lon.ravel(), lat.ravel())]).reshape(rr.shape)
          if inside.any():
              for kk in mixk:
                  mix[kk] = round(float((VR[kk][rr, cc][inside] / WGT[kk]).mean()), 3)
      # handgeschriebene Beschreibung derselben Kategorie übernehmen
      cur = None
      for cp, a in curated:
          if a['cat'] == k and k in handcats and cp.intersects(p):
              ov = cp.intersection(p).area
              if ov > 0.2 * min(cp.area, p.area) and p.buffer(0.002).contains(cp.representative_point()) and (cur is None or ov > cur[0]): cur = (ov, a)
      if cur and cur[1]['id'] in USED: cur = None
      if cur: USED.add(cur[1]['id'])
      nm = place_name(p, k)
      where = lage(p)
      if cur:
          a = cur[1]; name, lg, text, mod = a['name'], a['lage'], a['text'], a.get('modell', '')
      else:
          gem = where.split(', ')[-1]
          if gem != 'Innsbruck':
              name = CATL.get(k, 'Barriere') + ' ' + gem + (f' ({nm})' if nm and nm != gem else '')
          else:
              name = CATL.get(k, 'Barriere') + ' ' + (nm or where.split(',')[0])
          if nm and nm.lower().startswith(('gewerbegebiet', 'industrie', 'campus', 'universit', 'einkauf')): name = nm
          lg, text, mod = where, GENERIC.get(k, ''), MODELL.get(k, '')
          if k == 'wohnen' and mix:
              text = 'Wohngebiet. ' + SUBTXT[max(SUB, key=lambda q: mix.get(q, 0))]
      if k == 'barriere':
          name, lg = 'Flughafen Innsbruck', where
          text = 'Rollfeld und Flughafengelände (OSM aeroway=aerodrome): eine große, nicht durchquerbare Fläche zwischen Stadt und Inn.'
          mod = 'Barriere: Infrastrukturflächen trennen die Inseln der Stadt voneinander.'
      rings = [[[round(y, 5), round(x, 5)] for x, y in p.exterior.coords[:-1]]] + \
              [[[round(y, 5), round(x, 5)] for x, y in r.coords[:-1]] for r in p.interiors if Polygon(r).area * KX * KY > 15000]
      out.append({'id': f'{pre}{idx}', 'cat': k, 'name': name, 'lage': lg, 'text': text, 'modell': mod,
                  'ha': round(area_ha(p), 1), 'mix': mix, 'geb': bc, 'poi': pc, 'rings': rings, 'hand': bool(cur)})
  return out

out = describe(feats, MAIN + SUB, ('konsum', 'gewerbe', 'bildung', 'barriere'), 'f')
outw = describe(feats_sub, SUB + ['konsum', 'gewerbe', 'bildung', 'erholung'], tuple(SUB), 'w')
for o in out:   # Bauform-Anteile nur für Wohnflächen anzeigen
    if o['cat'] != 'wohnen':
        for q in SUB: o['mix'].pop(q, None)
    else:
        o['mix'].pop('wohnen', None)
json.dump(out, open(sys.argv[6], 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
json.dump(outw, open(sys.argv[6].replace('.json', '_wohnen.json'), 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
from collections import Counter
print(len(out), 'Flächen', Counter(o['cat'] for o in out), 'mit Handtext:', sum(o['hand'] for o in out))
print(len(outw), 'Wohn-Teilflächen', Counter(o['cat'] for o in outw), 'mit Handtext:', sum(o['hand'] for o in outw))

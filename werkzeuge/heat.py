"""Berechnet Heatmap-Raster (Dichteoberflächen) je Kategorie aus OpenStreetMap-Daten.

Aufruf:  python heat.py bld.json poi.json lu.json heat.json
Eingabe: Overpass-JSON (Gebäude mit Geometrie, POIs mit Zentrum, Landnutzung mit Geometrie)
Ausgabe: heat.json mit einem 0–255-Raster je Kategorie (base64), normiert auf das 99,5-%-Perzentil.
"""
import json, sys, math, base64
import numpy as np
from scipy.ndimage import gaussian_filter
from matplotlib.path import Path

S, N, W, E = 47.180, 47.322, 11.250, 11.530
CELL = 75.0                                   # Zellgröße in m
LAT0 = (S + N) / 2
MY = 111320.0
MX = 111320.0 * math.cos(math.radians(LAT0))
DLAT, DLON = CELL / MY, CELL / MX
H = int(math.ceil((N - S) / DLAT)); WD = int(math.ceil((E - W) / DLON))
N = S + H * DLAT; E = W + WD * DLON
CATS = ['konsum', 'gewerbe', 'gehoben', 'gemischt', 'gross', 'bildung', 'erholung']
WOHN = ('gehoben', 'gemischt', 'gross')   # zusätzlich als eine gemeinsame Kategorie 'wohnen'
G = {k: np.zeros((H, WD), np.float64) for k in CATS}

def cell(lat, lon):
    r = int((N - lat) / DLAT); c = int((lon - W) / DLON)
    return (r, c) if 0 <= r < H and 0 <= c < WD else None

def add(cat, lat, lon, w):
    rc = cell(lat, lon)
    if rc: G[cat][rc] += w

def ring_area_centroid(pts):
    xs = [(p['lon'] - W) * MX for p in pts]; ys = [(p['lat'] - S) * MY for p in pts]
    a = cx = cy = 0.0
    for i in range(len(xs) - 1):
        f = xs[i] * ys[i + 1] - xs[i + 1] * ys[i]
        a += f; cx += (xs[i] + xs[i + 1]) * f; cy += (ys[i] + ys[i + 1]) * f
    if abs(a) < 1e-9:
        return 0.0, pts[0]['lat'], pts[0]['lon']
    a *= 0.5
    return abs(a), S + cy / (6 * a) / MY, W + cx / (6 * a) / MX

# Zellmittelpunkte für Flächen-Rasterung
rr, cc = np.mgrid[0:H, 0:WD]
CLAT = N - (rr + 0.5) * DLAT; CLON = W + (cc + 0.5) * DLON
CENTERS = np.column_stack([CLON.ravel(), CLAT.ravel()])

def raster_poly(pts):
    lons = [p['lon'] for p in pts]; lats = [p['lat'] for p in pts]
    r0 = max(0, int((N - max(lats)) / DLAT) - 1); r1 = min(H, int((N - min(lats)) / DLAT) + 2)
    c0 = max(0, int((min(lons) - W) / DLON) - 1); c1 = min(WD, int((max(lons) - W) / DLON) + 2)
    if r0 >= r1 or c0 >= c1: return None
    sub = np.column_stack([CLON[r0:r1, c0:c1].ravel(), CLAT[r0:r1, c0:c1].ravel()])
    m = Path(np.column_stack([lons, lats])).contains_points(sub).reshape(r1 - r0, c1 - c0)
    out = np.zeros((H, WD), bool); out[r0:r1, c0:c1] = m
    return out

def rings_of(el):
    if el['type'] == 'way' and 'geometry' in el:
        g = el['geometry']
        if len(g) > 3 and g[0] == g[-1]: yield g
    elif el['type'] == 'relation':
        for m in el.get('members', []):
            g = m.get('geometry')
            if m.get('role') == 'outer' and g and len(g) > 3 and g[0] == g[-1]: yield g

raw = [json.load(open(p, encoding='utf8')) for p in sys.argv[1:4]]
bld, poi, lu = (r['elements'] for r in raw)
DATE = raw[0].get('osm3s', {}).get('timestamp_osm_base', '')[:10]

# --- Landnutzung (Fläche je Zelle = CELL² × Gewicht) ---
LU_W = {('landuse', 'industrial'): ('gewerbe', .35), ('landuse', 'commercial'): ('gewerbe', .2),
        ('landuse', 'retail'): ('konsum', .35), ('landuse', 'education'): ('bildung', .45),
        ('amenity', 'university'): ('bildung', .45), ('amenity', 'college'): ('bildung', .45),
        ('amenity', 'school'): ('bildung', .35),
        ('leisure', 'park'): ('erholung', .55), ('leisure', 'garden'): ('erholung', .35), ('leisure', 'playground'): ('erholung', .6),
        ('leisure', 'pitch'): ('erholung', .55), ('leisure', 'sports_centre'): ('erholung', .6), ('leisure', 'stadium'): ('erholung', .7),
        ('leisure', 'swimming_pool'): ('erholung', .6), ('leisure', 'water_park'): ('erholung', .7), ('leisure', 'golf_course'): ('erholung', .3),
        ('leisure', 'ice_rink'): ('erholung', .6), ('leisure', 'track'): ('erholung', .4), ('leisure', 'bathing_place'): ('erholung', .5),
        ('leisure', 'miniature_golf'): ('erholung', .5), ('leisure', 'dog_park'): ('erholung', .3), ('leisure', 'horse_riding'): ('erholung', .3),
        ('landuse', 'recreation_ground'): ('erholung', .5), ('landuse', 'allotments'): ('erholung', .35),
        ('tourism', 'zoo'): ('erholung', .7), ('tourism', 'theme_park'): ('erholung', .6), ('tourism', 'camp_site'): ('erholung', .35)}
resid = np.zeros((H, WD), bool)
cnt = {}
for el in lu:
    t = el.get('tags', {})
    for ring in rings_of(el):
        m = raster_poly(ring)
        if m is None: continue
        if t.get('landuse') == 'residential': resid |= m
        for (k, v), (cat, w) in LU_W.items():
            if t.get(k) == v:
                G[cat][m] += w * CELL * CELL; cnt[cat] = cnt.get(cat, 0) + 1

# --- Amtliche Flächenwidmung (Land Tirol, optional 5. Argument) ---
ZW = {'gewerbe': [('gewerbe', .7)], 'handel': [('konsum', .9)], 'kern': [('konsum', .35), ('gemischt', .25)],
      'misch': [('gemischt', .2), ('gewerbe', .25)], 'wohnmisch': [('gemischt', .25)], 'gefwohn': [('gross', .4)],
      'bildung': [('bildung', .8)], 'betrieb': [('gewerbe', .5)], 'gast': [('konsum', .2)], 'freizeit': [('erholung', .8)]}
zkat = np.full((H, WD), '', dtype=object)
if len(sys.argv) > 5:
    for ft in json.load(open(sys.argv[5], encoding='utf8'))['features']:
        k = ft['properties']['kat']; gm = ft['geometry']
        polys = gm['coordinates'] if gm['type'] == 'MultiPolygon' else [gm['coordinates']]
        for poly in polys:
            m = raster_poly([{'lat': y, 'lon': x} for x, y in poly[0]])
            if m is None: continue
            if k in ('wohn', 'wohnmisch', 'gefwohn', 'dorf', 'kern', 'misch'): resid |= m
            if k in ('gewerbe', 'handel', 'betrieb', 'bildung', 'kern', 'gefwohn'): zkat[m] = k
            for cat, w in ZW.get(k, []):
                G[cat][m] += w * CELL * CELL; cnt[cat] = cnt.get(cat, 0) + 1

# --- Gebäude (Grundfläche bzw. Geschoßfläche) ---
HOUSE = {'house', 'detached', 'semidetached_house', 'villa', 'bungalow', 'terrace', 'farm'}
APT = {'apartments', 'residential', 'dormitory'}
IND = {'industrial', 'warehouse', 'manufacture', 'factory', 'storage_tank', 'hangar_industrial'}
SHOP = {'retail', 'supermarket', 'kiosk', 'mall'}
COM = {'commercial', 'office'}
EDU = {'school', 'university', 'college', 'kindergarten'}
stats = {}
for el in bld:
    g = el.get('geometry'); t = el.get('tags', {})
    if not g or len(g) < 4: continue
    a, la, lo = ring_area_centroid(g if g[0] == g[-1] else g + [g[0]])
    if a < 25 or a > 60000: continue
    b = t.get('building', 'yes')
    try: lev = float(str(t.get('building:levels', '')).split(';')[0])
    except ValueError: lev = 0
    rc = cell(la, lo)
    if not rc: continue
    inres = resid[rc]; zk = zkat[rc]
    if b == 'yes' and zk in ('gewerbe', 'betrieb'):
        cat, w = 'gewerbe', a * (lev or 1.5)
    elif b == 'yes' and zk == 'handel':
        cat, w = 'konsum', a * 1.5
    elif b in HOUSE or (b == 'yes' and inres and a < 260 and (lev == 0 or lev <= 3)):
        cat, w = 'gehoben', a
    elif b in APT or (b == 'yes' and inres):
        L = lev or (4 if a < 1000 else 6)
        cat, w = ('gross', a * L) if (L >= 7 or a >= 1100) else ('gemischt', a * L)
    elif b in IND: cat, w = 'gewerbe', a
    elif b in SHOP: cat, w = 'konsum', a * 1.5
    elif b in COM: cat, w = 'gewerbe', a * .6
    elif b in EDU: cat, w = 'bildung', a * max(1, lev or 2)
    else: continue
    G[cat][rc] += w; stats[cat] = stats.get(cat, 0) + 1

# --- Punkte (Geschäfte, Gastronomie, Betriebe, Bildung) ---
def pos(el):
    if 'lat' in el: return el['lat'], el['lon']
    c = el.get('center'); return (c['lat'], c['lon']) if c else (None, None)
for el in poi:
    t = el.get('tags', {}); la, lo = pos(el)
    if la is None: continue
    s = t.get('shop'); am = t.get('amenity')
    if s:
        add('konsum', la, lo, 3000 if s in ('mall', 'department_store') else 800 if s == 'supermarket' else 300)
    elif am in ('restaurant', 'cafe', 'fast_food', 'bank', 'pharmacy', 'cinema', 'marketplace'):
        add('konsum', la, lo, 150)
    if t.get('leisure') in ('playground', 'pitch', 'sports_centre', 'swimming_pool', 'fitness_centre', 'climbing', 'ice_rink', 'stadium')        or t.get('tourism') in ('zoo', 'theme_park', 'camp_site', 'picnic_site', 'viewpoint'):
        add('erholung', la, lo, 400)
    if t.get('craft') or t.get('man_made') == 'works': add('gewerbe', la, lo, 300)
    if t.get('office'): add('gewerbe', la, lo, 150)
    if am in ('university', 'college', 'research_institute'): add('bildung', la, lo, 1500)
    elif am == 'school': add('bildung', la, lo, 800)
    elif am == 'library': add('bildung', la, lo, 300)
    elif am == 'kindergarten': add('bildung', la, lo, 200)

out = {'bounds': [[S, W], [N, E]], 'w': WD, 'h': H, 'cell': CELL, 'sigma_m': 0, 'date': '.'.join(DATE.split('-')[::-1]), 'cats': {}}
SIG = 2.6
out['sigma_m'] = round(SIG * CELL)
G['wohnen'] = sum(G[k] for k in WOHN)
for k in CATS + ['wohnen']:
    d = gaussian_filter(G[k], SIG, mode='constant')
    nz = d[d > d.max() * 0.002]
    ref = np.percentile(nz, 99.5) if nz.size else 1
    v = np.clip(d / ref, 0, 1)
    v[v < 0.02] = 0
    out['cats'][k] = base64.b64encode((v * 255).round().astype(np.uint8).tobytes()).decode()
    print(k, 'Gebäude', stats.get(k, 0), 'Landnutzung', cnt.get(k, 0), 'Zellen>0.3:', int((v > .3).sum()))
json.dump(out, open(sys.argv[4], 'w'))
print('Raster', WD, 'x', H)

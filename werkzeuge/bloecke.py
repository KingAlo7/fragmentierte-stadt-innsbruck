"""Inseln der fragmentierten Stadt aus amtlichen, straßengenauen Daten (statt geglätteter Heatmap-Blobs).

Aufruf: python bloecke.py roh/landnutzung.geojson roh/gebaeude.geojson daten/widmung.geojson lu.json poi.json daten/netz.json lines.geojson daten/bloecke.geojson

Grundlage
- tiris Landnutzung (Realnutzungskartierung Land Tirol, M 1:1000, CC BY 4.0): Straßen und Bahn sind eigene
  Flächen, die Siedlungsflächen sind daher Baublöcke, die von Straßen begrenzt werden.
- tiris Gebäude (Umrisse mit Höhe aus Laserscan): Bauform des Wohnens je Block.
- tiris Flächenwidmung und OSM (Schulen, Hochschulen, Geschäfte): Bildung und Konsum innerhalb gemischter Blöcke.

Regeln je Block (Landnutzungsklasse -> Kategorie)
- Wohnnutzung, Mischnutzung (allgemein/Landwirtschaft/Tourismus), Anwesen -> Wohnen;
  gemischte Blöcke mit Kern-/Handelswidmung und hoher Geschäftsdichte -> Konsum
- Industrie und Gewerbe -> Gewerbe (überwiegend als Einkaufszentrum/Handel gewidmet -> Konsum)
- Sonstige Nutzung: Handel -> Konsum
- Sonstige Nutzung -> Bildung, wenn mind. 30 % als Bildung gewidmet oder OSM-Schul-/Hochschulgelände; sonst nicht zugeordnet
- Anlagen (Grünanlagen, Sport, Golf, Camping, Erholung) -> Erholung & Freizeit; Schipisten am Berg bleiben außen vor
- Flugverkehr + OSM-Flughafengelände -> Barriere
In jedem Block mit überwiegend Bildungswidmung bzw. Schul-/Hochschulgelände -> Bildung.
Benachbarte Blöcke derselben Kategorie werden zu Inseln verschmolzen; Straßen trennen sie.
"""
import json, sys, math
from collections import Counter, defaultdict
from shapely.geometry import shape, mapping, Point, Polygon
from shapely.ops import unary_union, transform
from shapely.strtree import STRtree

fln, fgeb, fwid, flu, fpoi, fnet, flines, fout = sys.argv[1:9]
LAT0 = 47.26
KX, KY = 111320 * math.cos(math.radians(LAT0)), 111320.0
to_m = lambda g: transform(lambda x, y, z=None: (x * KX, y * KY), g)
to_ll = lambda g: transform(lambda x, y, z=None: (x / KX, y / KY), g)

def load(fn):
    return json.load(open(fn, encoding='utf8'))['features']

def geom(f):
    try:
        g = to_m(shape(f['geometry'])).buffer(0)
        return None if g.is_empty else g
    except Exception:
        return None

# --- Blöcke ---
KL = {'Siedlungstyp: Wohnnutzung': 'wohnen', 'Siedlungstyp: Mischnutzung allgemein': 'misch',
      'Siedlungstyp: Mischnutzung Landwirtschaft': 'wohnen', 'Siedlungstyp: Mischnutzung Tourismus': 'misch',
      'Siedlungstyp: Anwesen': 'wohnen', 'Siedlungstyp: Industrie und Gewerbe': 'gewerbe',
      'Siedlungstyp: Sonstige Nutzung: Handel': 'konsum', 'Siedlungstyp: Sonstige Nutzung': 'sonst',
      'Siedlungstyp: Sonstige Nutzung: Tourismus': 'sonst', 'Siedlungstyp: Sonstige Nutzung: Landwirtschaft': None,
      'Anlagen: Grünanlagen': 'erholung', 'Sport und Erholung: Sportanlage': 'erholung', 'Sport und Erholung: Golfplatz': 'erholung',
      'Anlagen: Camping': 'erholung', 'Anlagen: Erholung, Freizeit': 'erholung', 'Sport und Erholung: Schianlage': None,   # Pisten am Berg: kein Teil des Stadtgefüges
      'Flugverkehr': 'barriere'}
blocks = []
unk = Counter()
for f in load(fln):
    k = f['properties'].get('KLASSE')
    if k not in KL: unk[k] += 1; continue
    if KL[k] is None: continue
    g = geom(f)
    if g is not None: blocks.append({'g': g, 'ln': KL[k], 'klasse': k})
# Flughafen: in der Landnutzung nur Gebäude/Vorfeld (~25 ha) als Flugverkehr; Rollfeld aus OSM aeroway=aerodrome ergänzen
for el in json.load(open(flu, encoding='utf8'))['elements']:
    if el.get('tags', {}).get('aeroway') == 'aerodrome':
        g = to_m(Polygon([(p['lon'], p['lat']) for p in el['geometry']])).buffer(0)
        if g.area > 2e5: blocks.append({'g': g, 'ln': 'barriere', 'klasse': 'OSM aeroway=aerodrome'})
print(len(blocks), 'Blöcke', Counter(b['ln'] for b in blocks), 'unbekannt:', dict(unk))

# --- Widmung ---
wid = [(geom(f), f['properties']['kat']) for f in load(fwid)]
wid = [(g, k) for g, k in wid if g is not None]
wtree = STRtree([g for g, _ in wid])
def wshare(g):
    s = Counter()
    for i in wtree.query(g):
        wg, k = wid[i]
        if wg.intersects(g): s[k] += wg.intersection(g).area
    a = g.area or 1
    return {k: v / a for k, v in s.items()}

# --- OSM: Schul-/Hochschulgelände, Geschäfte ---
edu = []
for el in json.load(open(flu, encoding='utf8'))['elements']:
    t = el.get('tags', {})
    if t.get('amenity') in ('school', 'university', 'college') or t.get('landuse') == 'education':
        try: edu.append(to_m(Polygon([(p['lon'], p['lat']) for p in el['geometry']])).buffer(0))
        except Exception: pass
etree = STRtree(edu)
shops = []
for el in json.load(open(fpoi, encoding='utf8'))['elements']:
    t = el.get('tags', {}); c = el.get('center') or el
    if 'lat' not in c: continue
    if 'shop' in t or t.get('amenity') in ('restaurant', 'cafe', 'fast_food', 'bank', 'pharmacy', 'cinema', 'bar', 'pub'):
        shops.append(to_m(Point(c['lon'], c['lat'])))
stree = STRtree(shops)

# --- Gebäude (Höhe aus Laserscan) ---
geb = []
for f in load(fgeb):
    g = geom(f)
    if g is None or g.area < 40: continue
    h = f['properties'].get('GEB_HOEHE_MEDIAN') or f['properties'].get('GEB_HOEHE_MAX') or 0
    geb.append((g.representative_point(), g.area, float(h)))
gtree = STRtree([p for p, _, _ in geb])
def bauform(a, h):
    gs = max(1, round(h / 3.1))          # Geschoße aus der Gebäudehöhe
    if gs >= 7 or (a >= 1100 and gs >= 4): return 'gross', a * gs
    if a <= 260 and gs <= 3: return 'gehoben', a * gs
    return 'gemischt', a * gs

# --- Klassifizierung ---
stat = Counter()
for b in blocks:
    g = b['g']; ha = g.area / 1e4
    ws = wshare(g)
    eo = sum(edu[i].intersection(g).area for i in etree.query(g) if edu[i].intersects(g)) / (g.area or 1)
    ns = sum(1 for i in stree.query(g) if g.contains(shops[i]))
    cat = b['ln']
    if cat == 'misch':
        kern = ws.get('kern', 0) + ws.get('handel', 0)
        cat = 'konsum' if (kern >= 0.5 and ns / max(ha, 0.3) >= 6) or ws.get('handel', 0) >= 0.5 else 'wohnen'
    elif cat == 'gewerbe' and ws.get('handel', 0) >= 0.5:
        cat = 'konsum'
    if cat != 'barriere' and (ws.get('bildung', 0) >= 0.5 or eo >= 0.5 or (cat == 'sonst' and (ws.get('bildung', 0) >= 0.3 or eo >= 0.3))):
        cat = 'bildung'
    if cat == 'sonst' and ws:   # „sonstige Nutzung“ (Kliniken, Ämter …): nach der Widmung zuordnen, sonst später von den Nachbarn füllen
        dw = max(ws, key=ws.get)
        if ws[dw] >= 0.5:
            cat = {'kern': 'konsum', 'handel': 'konsum', 'gewerbe': 'gewerbe', 'betrieb': 'gewerbe', 'bildung': 'bildung',
                   'freizeit': 'erholung', 'wohn': 'wohnen', 'wohnmisch': 'wohnen', 'gefwohn': 'wohnen', 'misch': 'wohnen',
                   'dorf': 'wohnen'}.get(dw, 'sonst')
    b['cat'] = cat
    if cat == 'wohnen':
        fa = Counter()
        for i in gtree.query(g):
            p, a, h = geb[i]
            if g.contains(p):
                k, w = bauform(a, h); fa[k] += w
        b['sub'] = fa.most_common(1)[0][0] if fa else 'gehoben'
    stat[cat] += ha
print('Fläche je Kategorie (ha):', {k: round(v) for k, v in stat.items()})

# --- Generalisierung auf einem 10-m-Raster ---
# 1. Blöcke rastern. 2. Siedlungsgebiet = Blöcke + Straßen/Lücken dazwischen (Schließen mit 30 m, Löcher < 3 ha füllen).
# 3. Straßen, Lücken und nicht zuordenbare Blöcke erhalten die Nutzung des nächstgelegenen Blocks.
# 4. Mehrheitsfilter (70 m) gegen Flickenteppich; Flecken unter MIN_HA gehen an die umgebende Nutzung.
# 5. Vektorisieren mit gemeinsamen Grenzen (keine Lücken, keine Überlappung); nur Hauptstraßen (OSM secondary+),
#    Autobahn, Bahn und Inn teilen die Gebiete – als feine Linie, die Straßenfläche selbst ist gefüllt.
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
import contourpy
from shapely.geometry import LineString
RES = 10.0
MIN_HA, MIN_HA_SUB = 2.0, 1.0
GEM = [(to_m(shape(f['geometry'])).buffer(0), f['properties']['name']) for f in json.load(open('../boundaries.geojson', encoding='utf8'))['features']
       if f['properties']['kind'] == 'gemeinde']
STUDY = unary_union([g for g, _ in GEM])
X0, Y0, X1, Y1 = STUDY.bounds
WR, HR = int((X1 - X0) / RES) + 1, int((Y1 - Y0) / RES) + 1
def px(ring): return [((x - X0) / RES, (Y1 - y) / RES) for x, y in ring.coords]
def raster(items, order):
    img = Image.new('I', (WR, HR), 0); dr = ImageDraw.Draw(img)
    for k in order:
        for g in items.get(k, []):
            for p in (g.geoms if hasattr(g, 'geoms') else [g]):
                if p.geom_type != 'Polygon': continue
                dr.polygon(px(p.exterior), fill=order.index(k) + 1)
                for r in p.interiors: dr.polygon(px(r), fill=0)
    return np.array(img, dtype=np.int32)
def fuellen(lab, mask):
    """Zellen ohne Wert innerhalb von mask erhalten den Wert der nächsten belegten Zelle."""
    if not (lab > 0).any(): return lab
    _, (ir, ic) = ndi.distance_transform_edt(lab == 0, return_indices=True)
    out = lab[ir, ic]; out[~mask] = 0
    return out
def mehrheit(lab, n, mask, size):
    sc = np.stack([ndi.uniform_filter((lab == i).astype(np.float32), size) for i in range(1, n + 1)])
    out = sc.argmax(0) + 1; out[~mask] = 0
    return out
def kleine_weg(lab, n, mask, min_cells, runden=3):
    for _ in range(runden):
        changed = False
        for i in range(1, n + 1):
            cc, m = ndi.label(lab == i)
            if not m: continue
            sz = ndi.sum(np.ones_like(cc), cc, index=np.arange(1, m + 1))
            small = np.isin(cc, np.where(sz < min_cells)[0] + 1)
            if small.any(): lab[small] = 0; changed = True
        lab = fuellen(lab, mask)
        if not changed: break
    return lab

MAINK = ['wohnen', 'sonst', 'gewerbe', 'konsum', 'erholung', 'bildung', 'barriere']   # Malreihenfolge: später gewinnt
lab = raster({k: [b['g'] for b in blocks if b['cat'] == k] for k in MAINK}, MAINK)
occ = lab > 0
siedl = ndi.binary_closing(occ, structure=np.ones((3, 3)), iterations=3) | occ
holes = ndi.binary_fill_holes(siedl) & ~siedl
hc, hn = ndi.label(holes)
if hn:
    hs = ndi.sum(np.ones_like(hc), hc, index=np.arange(1, hn + 1))
    siedl |= np.isin(hc, np.where(hs * RES * RES < 3e4)[0] + 1)
study_r = raster({'s': [STUDY]}, ['s']) > 0
siedl &= study_r
lab[lab == MAINK.index('sonst') + 1] = 0              # nicht zuordenbare Blöcke wie Straßen behandeln
lab = fuellen(lab, siedl)
lab = mehrheit(lab, len(MAINK), siedl, 7)
lab = kleine_weg(lab, len(MAINK), siedl, MIN_HA * 1e4 / RES ** 2)
SUBK = ['gehoben', 'gemischt', 'gross']
wmask = lab == MAINK.index('wohnen') + 1
sl = raster({k: [b['g'] for b in blocks if b.get('sub') == k] for k in SUBK}, SUBK)
sl[~wmask] = 0
sl = fuellen(sl, wmask); sl = mehrheit(sl, 3, wmask, 7); sl = kleine_weg(sl, 3, wmask, MIN_HA_SUB * 1e4 / RES ** 2)

cuts = []
for e in json.load(open(fnet, encoding='utf8'))['edges']:
    if e['k'] < 4: continue
    g = e['g']; pts = []; la, lo = 0, 0
    for i in range(0, len(g), 2):
        la += g[i]; lo += g[i + 1]; pts.append((lo / 1e5 * KX, la / 1e5 * KY))
    if len(pts) > 1: cuts.append(LineString(pts))
for f in json.load(open(flines, encoding='utf8'))['features']:
    cuts.append(to_m(shape(f['geometry'])))
CUT = unary_union(cuts).buffer(1.0)
def vektor(lab, keys, min_ha):
    n = len(keys)
    M = np.stack([ndi.gaussian_filter((lab == i).astype(np.float32), 1.0) for i in range(0, n + 1)])
    out = []
    for i in range(1, n + 1):
        if not (lab == i).any(): continue
        f = np.pad(M[i] - np.delete(M, i, axis=0).max(0), 1, constant_values=-1)
        pts, offs = contourpy.contour_generator(z=f, fill_type=contourpy.FillType.OuterOffset).filled(0, 10)
        for P_, O in zip(pts, offs):
            rings = [[(X0 + (x - 1 + .5) * RES, Y1 - (y - 1 + .5) * RES) for x, y in P_[O[j]:O[j + 1]]] for j in range(len(O) - 1)]
            try: pg = Polygon(rings[0], rings[1:]).buffer(0)
            except Exception: continue
            q = pg.difference(CUT)
            out += [(keys[i - 1], x) for x in (q.geoms if hasattr(q, 'geoms') else [q]) if x.geom_type == 'Polygon' and x.area / 1e4 >= min_ha]
    return out
main = vektor(lab, MAINK, 0.5)
sub = vektor(sl, SUBK, 0.3)
print('Siedlungsgebiet', round(siedl.sum() * RES * RES / 1e4), 'ha; zugeordnet', round((lab > 0).sum() * RES * RES / 1e4), 'ha')

# an Gemeindegrenzen teilen (jede Insel gehört genau einer Gemeinde), außerhalb des Untersuchungsgebiets weglassen
GEM = [(to_m(shape(f['geometry'])).buffer(0), f['properties']['name']) for f in json.load(open('../boundaries.geojson', encoding='utf8'))['features']
       if f['properties']['kind'] == 'gemeinde']
def nach_gemeinde(L):
    out = []
    for k, p in L:
        for gg, gn in GEM:
            if not gg.intersects(p): continue
            q = gg.intersection(p)
            out += [(k, x, gn) for x in (q.geoms if hasattr(q, 'geoms') else [q]) if x.geom_type == 'Polygon' and x.area >= 2500]
    return out
main, sub = nach_gemeinde(main), nach_gemeinde(sub)
main = [m for m in main if m[0] != 'sonst']

# Kennzahlen je Insel: vorherrschende Landnutzungsklasse, Bauform-Anteile nach Geschoßfläche (amtliche Gebäude)
btree = STRtree([b['g'] for b in blocks])
def kennzahlen(p):
    kl = Counter()
    for i in btree.query(p):
        if blocks[i]['g'].intersects(p): kl[blocks[i]['klasse']] += blocks[i]['g'].intersection(p).area
    fa, n = Counter(), Counter()
    for i in gtree.query(p):
        q, a, h = geb[i]
        if p.contains(q):
            k, w = bauform(a, h); fa[k] += w; n[k] += 1
    T = sum(fa.values()) or 1
    return {'klasse': kl.most_common(1)[0][0].replace('Siedlungstyp: ', '') if kl else '',
            'bf': {k: round(v / T, 3) for k, v in fa.items()}, 'ngeb': dict(n), 'gfl': round(sum(fa.values()))}
print(len(main), 'Inseln', Counter(k for k, _, _ in main), '|', len(sub), 'Wohn-Teilflächen', Counter(k for k, _, _ in sub))
feats = [{'type': 'Feature', 'properties': dict(cat=k, ebene=e, gem=gn, **kennzahlen(p)), 'geometry': mapping(to_ll(p.simplify(2.0)))}
         for e, L in (('haupt', main), ('wohnen', sub)) for k, p, gn in L]
json.dump({'type': 'FeatureCollection', 'features': feats}, open(fout, 'w', encoding='utf8'), separators=(',', ':'))

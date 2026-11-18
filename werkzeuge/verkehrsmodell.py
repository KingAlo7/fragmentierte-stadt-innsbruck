"""Einfaches Verkehrsmodell für alle Straßen (Gravitationsmodell + Umlegung), kalibriert an Zählstellen.

Aufruf: python verkehrsmodell.py auszug.osm.pbf bld.json poi.json daten/traffic.json daten/profiles.json daten/netz.json

Schritte
1. Straßennetz aus OSM (Autobahn bis Wohnstraße), geteilt an Kreuzungen; Fahrzeit je Straßenklasse/Tempolimit.
2. Wohn-, Arbeits- und Versorgungsmassen je Netzknoten aus Gebäudegrundfläche × Geschoßen und POIs.
3. Fahrten (Gravitationsmodell) von Wohnzonen (300-m-Raster) zu Arbeits-/Versorgungsorten und zurück,
   dazu Quell-/Zielverkehr über die Einfallstraßen am Gebietsrand und Durchgangsverkehr zwischen ihnen.
4. Umlegung auf kürzeste Wege mit Kapazitätsbremse (BPR), 2 Durchgänge.
5. Kalibrierung: nicht-negative Kleinste-Quadrate-Anpassung der Komponenten an die Zählwerte (JDTV je Richtung).
6. Tagesgang: Stundenwerte jeder Komponente (Morgen-, Abendpendeln, Versorgung, Durchgang) werden aus den
   gemessenen Stundenwerten der Zählstellen geschätzt und leicht zeitlich geglättet.
"""
import json, sys, math, time
import numpy as np
import osmium
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.optimize import nnls
from scipy.spatial import cKDTree
from shapely.geometry import shape, Point
from shapely.ops import unary_union

T0 = time.time()
def log(*a): print(f'[{time.time()-T0:5.0f}s]', *a, flush=True)
S, W, N, E = 47.170, 11.235, 47.340, 11.545
KX, KY = 111320 * math.cos(math.radians(47.26)), 111320.0
CLS = {  # Klasse: (km/h, Kapazität Kfz/h je Richtung, Rang für die Darstellung)
 'motorway': (100, 3600, 7), 'trunk': (70, 2000, 6), 'primary': (50, 1600, 5), 'secondary': (45, 1100, 4),
 'tertiary': (40, 800, 3), 'unclassified': (30, 500, 2), 'residential': (25, 400, 1), 'living_street': (10, 200, 0),
 'motorway_link': (50, 1500, 6), 'trunk_link': (40, 1200, 5), 'primary_link': (35, 1000, 5),
 'secondary_link': (35, 900, 4), 'tertiary_link': (30, 700, 3)}
pbf, bldf, poif, trf, prf, outf = sys.argv[1:7]

STUDY = unary_union([shape(f['geometry']).buffer(0) for f in json.load(open('../boundaries.geojson', encoding='utf8'))['features']
                     if f['properties']['kind'] == 'gemeinde']).buffer(0.004)

# ---------------- 1. Netz ----------------
class WH(osmium.SimpleHandler):
    def __init__(s):
        super().__init__(); s.ways = []
    def way(s, w):
        hw = w.tags.get('highway')
        if hw not in CLS: return
        if w.tags.get('access') in ('private', 'no') or w.tags.get('motor_vehicle') in ('no', 'private'): return
        try: nodes = [(n.ref, n.location.lat, n.location.lon) for n in w.nodes]
        except Exception: return
        if len(nodes) < 2: return
        s.ways.append((hw, {k: w.tags.get(k) for k in ('name', 'ref', 'oneway', 'junction', 'maxspeed') if w.tags.get(k)}, nodes))
h = WH(); h.apply_file(pbf, locations=True)
ways = [x for x in h.ways if any(S < la < N and W < lo < E for _, la, lo in x[2])]
cnt = {}
for _, _, nd in ways:
    for i, (r, _, _) in enumerate(nd): cnt[r] = cnt.get(r, 0) + (2 if i in (0, len(nd) - 1) else 1)
nid, ncoord = {}, []
def node(r, la, lo):
    if r not in nid: nid[r] = len(ncoord); ncoord.append((la, lo))
    return nid[r]
def seglen(g): return sum(math.hypot((g[i][0] - g[i-1][0]) * KY, (g[i][1] - g[i-1][1]) * KX) for i in range(1, len(g)))
EF, ET, EL, EC, EG, EO, EN, ER, ES = [], [], [], [], [], [], [], [], []
for hw, t, nd in ways:
    ow = t.get('oneway') in ('yes', '1', 'true') or t.get('junction') in ('roundabout', 'circular') or hw in ('motorway', 'motorway_link')
    if t.get('oneway') == '-1': nd = nd[::-1]; ow = True
    try: ms = float((str(t.get('maxspeed', '')).split() or ['0'])[0])
    except ValueError: ms = 0
    sp = min(ms, CLS[hw][0] * 1.1) if ms > 0 else CLS[hw][0]
    st = 0
    for i in range(1, len(nd)):
        if cnt.get(nd[i][0], 0) >= 2 or i == len(nd) - 1:
            g = [(la, lo) for _, la, lo in nd[st:i + 1]]
            mid = g[len(g) // 2]
            if STUDY.contains(Point(mid[1], mid[0])):
                a, b = node(*nd[st]), node(*nd[i])
                if a != b:
                    EF.append(a); ET.append(b); EL.append(max(seglen(g), 1.0)); EC.append(hw); EG.append(g)
                    EO.append(ow); EN.append(t.get('name', '')); ER.append(t.get('ref', '')); ES.append(sp)
            st = i
NE, NN = len(EF), len(ncoord); ncoord = np.array(ncoord)
AU, AV, AE, AD = [], [], [], []
for e in range(NE):
    AU.append(EF[e]); AV.append(ET[e]); AE.append(e); AD.append(0)
    if not EO[e]: AU.append(ET[e]); AV.append(EF[e]); AE.append(e); AD.append(1)
deg = np.bincount(np.r_[EF, ET], minlength=NN)
GWn = {}
for e in range(NE):
    if CLS[EC[e]][2] < 3 or EC[e].endswith('_link'): continue
    for n in (EF[e], ET[e]):
        if deg[n] == 1:
            ref = (ER[e].split(';')[0].replace(' ', '') or EN[e] or EC[e])
            la, lo = ncoord[n]
            side = 'W' if lo < 11.33 else 'O' if lo > 11.47 else ('S' if la < 47.25 else 'N')
            GWn.setdefault(ref + '-' + side, set()).add(n)
# je Einfallstraße ein virtueller Knoten, verbunden mit allen Fahrbahnenden (beide Richtungen)
GW = {}
for g, ns in GWn.items():
    vn = NN + len(GW); GW[g] = [vn]
    for n in ns:
        AU += [vn, n]; AV += [n, vn]; AE += [-1, -1]; AD += [0, 0]
NV = len(GW)
AU, AV, AE, AD = map(np.array, (AU, AV, AE, AD)); NA = len(AU)
NN0 = NN; NN = NN + NV
ncoord = np.vstack([ncoord, np.array([ncoord[sorted(ns)[0]] for ns in GWn.values()]).reshape(-1, 2)])
# empfundene Fahrzeit: Wohn- und Nebenstraßen werden gemieden (Routenwahl bevorzugt Hauptstraßen)
PEN = {'residential': 1.8, 'living_street': 3.0, 'unclassified': 1.4, 'tertiary': 1.12}
tfree = np.array([EL[e] / (ES[e] / 3.6) / 60 * PEN.get(EC[e], 1.0) if e >= 0 else 0.05 for e in AE])
cap = np.array([CLS[EC[e]][1] if e >= 0 else 1e5 for e in AE], float)
_, lab = connected_components(csr_matrix((np.ones(NA), (AU, AV)), shape=(NN, NN)), directed=True, connection='strong')
ok = lab == np.bincount(lab).argmax()
amap = {}
for i in range(NA):
    k = (AU[i], AV[i])
    if k not in amap or tfree[i] < tfree[amap[k]]: amap[k] = i
log(f'Netz: {NE} Abschnitte, {NA} Fahrtrichtungen, {NN} Knoten, {ok.sum()} im Hauptnetz')

# ---------------- 2. Massen ----------------
nonmw = np.zeros(NN, bool)
for e in range(NE):
    if not EC[e].startswith(('motorway', 'trunk')): nonmw[EF[e]] = nonmw[ET[e]] = True
cand = np.where(ok & nonmw)[0]
tree = cKDTree(np.c_[ncoord[cand, 0] * KY, ncoord[cand, 1] * KX])
home = np.zeros(NN); work = np.zeros(NN); shop = np.zeros(NN)
HOUSE = {'house', 'detached', 'semidetached_house', 'villa', 'bungalow', 'terrace', 'farm'}
APT = {'apartments', 'residential', 'dormitory'}
WORK = {'commercial', 'office', 'industrial', 'warehouse', 'manufacture', 'retail', 'supermarket', 'school', 'university',
        'college', 'hospital', 'public', 'government', 'civic', 'kindergarten', 'hotel', 'service'}
def area(g):
    return abs(sum((g[i]['lon'] * KX) * (g[i+1]['lat'] * KY) - (g[i+1]['lon'] * KX) * (g[i]['lat'] * KY) for i in range(len(g) - 1))) / 2
pts, wh, ww = [], [], []
for el in json.load(open(bldf, encoding='utf8'))['elements']:
    g = el['geometry']; a = area(g)
    if a < 25 or a > 60000: continue
    tg = el['tags']; b = tg.get('building', 'yes')
    try: lev = float(str(tg.get('building:levels', '0')).split(';')[0])
    except ValueError: lev = 0
    if b in HOUSE: fh, fw, L = 1, 0, lev or 2
    elif b in APT: fh, fw, L = 1, .05, lev or 4
    elif b in WORK: fh, fw, L = 0, 1, lev or 2
    elif b == 'yes': fh, fw, L = .6, .4, lev or (2 if a < 300 else 4)
    else: continue
    pts.append((sum(p['lat'] for p in g) / len(g) * KY, sum(p['lon'] for p in g) / len(g) * KX)); wh.append(a * L * fh); ww.append(a * L * fw)
_, ix = tree.query(np.array(pts)); np.add.at(home, cand[ix], wh); np.add.at(work, cand[ix], ww)
pp, pw = [], []
for el in json.load(open(poif, encoding='utf8'))['elements']:
    c = el.get('center') or el
    if 'lat' not in c: continue
    s_ = el['tags'].get('shop')
    pp.append((c['lat'] * KY, c['lon'] * KX)); pw.append(2500 if s_ in ('mall', 'department_store') else 800 if s_ == 'supermarket' else 200)
_, ix = tree.query(np.array(pp)); np.add.at(shop, cand[ix], pw)
work += 0.5 * shop
# Echte Größenordnung je Gemeinde (Statistik Austria, Abgestimmte Erwerbsstatistik 2024):
# Wohnmasse -> Einwohner, Arbeitsmasse -> Beschäftigte am Arbeitsort
if len(sys.argv) > 7:
    from shapely.prepared import prep
    GS = json.load(open(sys.argv[7], encoding='utf8'))
    gems = [(f['properties']['name'], prep(shape(f['geometry']).buffer(0)))
            for f in json.load(open('../boundaries.geojson', encoding='utf8'))['features'] if f['properties']['kind'] == 'gemeinde']
    gidx = np.full(NN, -1)
    for n in np.where((home > 0) | (work > 0))[0]:
        pt = Point(ncoord[n, 1], ncoord[n, 0])
        for i, (nm, g) in enumerate(gems):
            if g.contains(pt): gidx[n] = i; break
    for i, (nm, _) in enumerate(gems):
        if nm not in GS: continue
        m = gidx == i
        if home[m].sum() > 0: home[m] *= GS[nm]['bev'] / home[m].sum()
        if work[m].sum() > 0: work[m] *= GS[nm]['besch'] / work[m].sum()
        log(f"   {nm}: {GS[nm]['bev']} Einwohner, {GS[nm]['besch']} Beschäftigte, Knoten {m.sum()}")
    log('   ohne Gemeinde:', int(((gidx < 0) & ((home > 0) | (work > 0))).sum()), 'Knoten')
    # Knoten außerhalb der Gemeinden (Randstreifen): deren Verkehr läuft über die Einfallstraßen
    home[gidx < 0] = 0; work[gidx < 0] = 0; shop[gidx < 0] = 0
visit = shop / max(shop.sum(), 1) * home.sum() * 0.5 + 0.25 * home + 0.1 * work
log(f'Massen: Wohnen {home.sum()/1e6:.1f} Mio m², Arbeit {work.sum()/1e6:.1f} Mio m²')

# Zonen (300 m) für die Wohnseite
ZS = 300.0
zk = ((ncoord[:, 0] - S) * KY // ZS).astype(int) * 1000 + ((ncoord[:, 1] - W) * KX // ZS).astype(int)
zones = {}
for n in np.where((home > 0) & ok)[0]: zones.setdefault(zk[n], []).append(n)
ZN, ZM = [], []
for ns in zones.values():
    ns = np.array(ns); m = home[ns]
    cy, cx = (ncoord[ns, 0] * m).sum() / m.sum(), (ncoord[ns, 1] * m).sum() / m.sum()
    ZN.append(ns[np.argmin((ncoord[ns, 0] - cy) ** 2 + (ncoord[ns, 1] - cx) ** 2)]); ZM.append(m.sum())
ZN, ZM = np.array(ZN), np.array(ZM) / np.sum(ZM)
log('Einfallstraßen:', ', '.join(GW))

# ---------------- 3./4. Umlegung ----------------
def assign(times, origins, dlist, reverse=False, batch=40):
    """origins: Knoten-Array + Gewichte; dlist: [(Zielmasse je Knoten, beta)] -> Flüsse je Arc, eine Spalte je Ziel."""
    G = csr_matrix((times, (AV, AU) if reverse else (AU, AV)), shape=(NN, NN))
    on, om = origins
    flows = np.zeros((len(dlist), NA))
    for b0 in range(0, len(on), batch):
        D, P = dijkstra(G, directed=True, indices=on[b0:b0 + batch], return_predecessors=True)
        for r in range(D.shape[0]):
            d, pred = D[r], P[r]; fin = np.isfinite(d)
            dd = np.where(fin, d, 1e9)
            accs = []
            for dm, beta in dlist:
                wgt = dm * np.exp(-beta * dd); sw = wgt.sum()
                accs.append(om[b0 + r] * wgt / sw if sw > 0 else np.zeros(NN))
            order = np.argsort(-dd); order = order[fin[order]]
            par = pred[order]
            # Teilbaumsummen (Knoten weiter weg zuerst): Nachfrage zum Ursprung zurückreichen
            pairs = [(v, p) for v, p in zip(order.tolist(), par.tolist()) if p >= 0]
            if len(accs) == 1:
                a0 = accs[0].tolist()
                for v, p in pairs: a0[p] += a0[v]
                A = np.array([a0]).T
            else:
                a0, a1 = accs[0].tolist(), accs[1].tolist()
                for v, p in pairs:
                    a0[p] += a0[v]; a1[p] += a1[v]
                A = np.array([a0, a1]).T
            m = (pred >= 0) & fin; vv = np.where(m)[0]; uu = pred[vv]
            keys = zip(vv, uu) if reverse else zip(uu, vv)
            ai = np.fromiter((amap[k] for k in keys), int, len(vv))
            for j in range(len(dlist)): np.add.at(flows[j], ai, A[vv, j])
    return flows

def run_all(times):
    C = {}
    z = (ZN, ZM)
    f = assign(times, z, [(work, .05), (visit, .10)])            # Wohnung -> Arbeit / Erledigung
    C['int_m'], C['int_o1'] = f
    f = assign(times, z, [(work, .05), (visit, .10)], reverse=True)   # zurück nach Hause
    C['int_e'], C['int_o2'] = f
    for g, ns in GW.items():
        o = (np.array(ns), np.ones(len(ns)) / len(ns))
        fi = assign(times, o, [(work + home * .3, .03)])[0]
        fo = assign(times, o, [(work + home * .3, .03)], reverse=True)[0]
        C['gw:' + g] = (fi, fo)
    # Durchgangsverkehr zwischen Einfallstraßen (Ziel = andere Einfallstraßen)
    gwn = np.zeros(NN)
    for g, ns in GW.items():
        w_ = 1.0 if g.startswith(('A12', 'A13')) else 0.15
        gwn[ns] += w_ / len(ns)
    allg = np.array(sorted({n for ns in GW.values() for n in ns}))
    C['thr'] = assign(times, (allg, gwn[allg] / gwn[allg].sum()), [(gwn, .0)])[0]
    return C

# ---------------- 5. Kalibrierung ----------------
TR = json.load(open(trf, encoding='utf8')); PR = json.load(open(prf, encoding='utf8'))
def edge_dist(e, la, lo):
    g = EG[e]; return min(math.hypot((a - la) * KY, (b - lo) * KX) for a, b in g)
def heading(g, la, lo):
    i = min(range(len(g) - 1), key=lambda i: math.hypot(((g[i][0] + g[i+1][0]) / 2 - la) * KY, ((g[i][1] + g[i+1][1]) / 2 - lo) * KX))
    return ((g[i+1][0] - g[i][0]) * KY, (g[i+1][1] - g[i][1]) * KX)
eidx = cKDTree(np.array([(np.mean([p[0] for p in g]) * KY, np.mean([p[1] for p in g]) * KX) for g in EG]))
OBS = []   # (Station, Richtung 0/1, Arc, Tageswert, Stundenwerte werktag/wochenende)
for s in TR:
    ref = s['road'].split(' ')[0] + s['road'].split(' ')[1] if s['road'][1] == ' ' else ''
    la, lo = s['pos']
    # Richtung 1 = Vorwärtsrichtung des Korridors aus traffic.json (zur Zielrichtung orientiert)
    best = min((p for p in s['paths']), key=lambda p: min(math.hypot((a - la) * KY, (b - lo) * KX) for a, b in p['c']))
    h1 = heading(best['c'], la, lo)
    near = eidx.query_ball_point((la * KY, lo * KX), 400)
    near = [e for e in near if ER[e].replace(' ', '').split(';')[0] == ref and edge_dist(e, la, lo) < (220 if ref[0] == 'A' else 120)]
    if not near: log('  keine Kante für', s['name']); continue
    tot = [sum(d['werktag']) for d in s['dirs']]
    for di in range(len(s['dirs'])):
        cands = []
        for e in near:
            for a in np.where(AE == e)[0]:
                he = heading(EG[e], la, lo) if AD[a] == 0 else tuple(-x for x in heading(EG[e], la, lo))
                dot = he[0] * h1[0] + he[1] * h1[1]
                if (dot > 0) == (di == 0): cands.append((edge_dist(e, la, lo), a))
        if not cands: continue
        a = min(cands)[1]
        share = tot[di] / sum(tot) if len(s['dirs']) > 1 else 1.0
        OBS.append((s, di, a, s['jdtv'] * share, s['dirs'][di]['werktag'], s['dirs'][di]['wochenende']))
log(f'{len(OBS)} Zählwerte (Station × Richtung) zugeordnet')

# Vorwissen über die Einfallstraßen (Kfz/Tag laut Zählstellen knapp außerhalb, gerundet); unbekannt = 2000
GW_PRIOR = {'B171-W': 3400, 'B177-W': 7500, 'L11-W': 6000, 'L12-W': 4000, 'L13-W': 11000, 'B182-S': 4100, 'B183-S': 14000,
            'L9-S': 3000, 'L9-O': 3400, 'L8-O': 8200, 'B171-O': 20000, 'L227-S': 3000, 'L38-S': 2000, 'Salzburger Straße-O': 8000}
def design(C):
    cols, names = [], []
    cols.append(C['int_m'] + C['int_e'] + 1.2 * (C['int_o1'] + C['int_o2'])); names.append('Binnenverkehr')
    land = np.zeros(NA)
    for k, v in C.items():
        if not k.startswith('gw:'): continue
        g = k[3:]
        if g.split('-')[0] in ('A12', 'A13'):
            cols.append(v[0] + v[1]); names.append(g)
        else:
            land += GW_PRIOR.get(g, 2000) / 10000 * (v[0] + v[1])
    cols.append(land); names.append('Einfallstraßen (Landes-/Bundesstraßen)')
    cols.append(C['thr']); names.append('Durchgang')
    return np.array(cols), names

def calibrate(C):
    X, names = design(C)
    ai = np.array([o[2] for o in OBS]); y = np.array([o[3] for o in OBS])
    wgt = 1 / np.sqrt(y)
    x, _ = nnls(X[:, ai].T * wgt[:, None], y * wgt, maxiter=5000)
    # robust: grobe Ausreißer (Faktor > 2,5 daneben, z. B. falsch zugeordnete Fahrtrichtung) beim 2. Schritt schwächer gewichten
    for _ in range(2):
        r = np.abs(np.log(np.maximum(X[:, ai].T @ x, 1) / y))
        w2 = wgt * np.where(r > np.log(2.5), 0.2, 1.0)
        x, _ = nnls(X[:, ai].T * w2[:, None], y * w2, maxiter=5000)
    pred = X[:, ai].T @ x
    return x, names, pred, y

times = tfree.copy()
for it in range(2):
    C = run_all(times)
    x, names, pred, y = calibrate(C)
    X, _ = design(C)
    F = x @ X
    err = np.abs(pred - y) / y
    log(f'Durchgang {it+1}: mittlere Abweichung {np.mean(err)*100:.0f} %, Median {np.median(err)*100:.0f} %, R² {1-np.sum((pred-y)**2)/np.sum((y-y.mean())**2):.2f}')
    times = tfree * (1 + 0.15 * (0.09 * F / cap) ** 4)
    times = np.minimum(times, tfree * 6)
for n_, v in zip(names, x): log(f'   Faktor {n_}: {v:.3g}')

# ---------------- 6. Tagesgang je Komponente ----------------
# Komponenten je Arc: Morgen (Hinweg Pendeln), Abend (Rückweg), Erledigung, Durchgang
ix = {n_: i for i, n_ in enumerate(names)}
xi = x[ix['Binnenverkehr']]
mor = xi * C['int_m']; eve = xi * C['int_e']; oth = 1.2 * xi * (C['int_o1'] + C['int_o2']); thr = x[ix['Durchgang']] * C['thr']
for k, v in C.items():
    if not k.startswith('gw:'): continue
    g = k[3:]
    f_ = x[ix[g]] if g in ix else x[ix['Einfallstraßen (Landes-/Bundesstraßen)']] * GW_PRIOR.get(g, 2000) / 10000
    mor += 0.6 * f_ * v[0]; oth += 0.4 * f_ * (v[0] + v[1]); eve += 0.6 * f_ * v[1]
COMP = np.array([mor, eve, oth, thr])
prof = {}
for key, kk in (('werktag', 4), ('wochenende', 5)):
    P = np.zeros((4, 24))
    Xo = np.array([COMP[:, o[2]] for o in OBS])
    for hh in range(24):
        yh = np.array([o[kk][hh] for o in OBS])
        # Anteil je Stunde, Summe über den Tag ~ 1 (pro Komponente)
        p, _ = nnls(Xo, yh); P[:, hh] = p
    # zeitlich glätten (gleitend über 3 Stunden, zyklisch) -> weniger Einfluss einzelner Ausreißer
    P = 0.25 * np.roll(P, 1, 1) + 0.5 * P + 0.25 * np.roll(P, -1, 1)
    # mittlerer gemessener Verlauf (Summe aller Zählwerte) als Rückfall und zur Stabilisierung
    allh = np.array([[o[kk][hh] for hh in range(24)] for o in OBS]).sum(0); mean = allh / allh.sum()
    dayfac = np.mean([sum(o[kk]) / o[3] for o in OBS])          # Werktag/Wochenende gegenüber JDTV
    for c in range(4):
        sh = P[c] / P[c].sum() if P[c].sum() > 0 else mean
        P[c] = (0.7 * sh + 0.3 * mean) * dayfac
    prof[key] = np.round(P, 5).tolist()
    log(key, 'Tagessummen je Komponente:', np.round(P.sum(1), 2))

# ---------------- 7. Anpassung an die Zählstellen ----------------
# Verhältnis gemessen/Modell je Zählstelle; auf derselben Straße (gleiche Nummer) mit Abstand abklingend übertragen.
raw = COMP.sum(0).copy()
emid = np.array([(np.mean([p[0] for p in g]), np.mean([p[1] for p in g])) for g in EG])
num = np.zeros(NE); den = np.zeros(NE) + 0.35          # Grundgewicht -> weit weg: Faktor 1 (reines Modell)
exact = {}
for o in OBS:
    s_, di, a, yv = o[0], o[1], o[2], o[3]
    mv = max(raw[a], 1.0); r = float(np.clip(yv / mv, 0.2, 5.0)); exact[a] = r
    ref = ER[AE[a]].replace(' ', '').split(';')[0]
    la, lo = s_['pos']
    d = np.hypot((emid[:, 0] - la) * KY, (emid[:, 1] - lo) * KX)
    same = np.array([ER[e].replace(' ', '').split(';')[0] == ref for e in range(NE)])
    w = np.where(same, np.exp(-d / 1800), np.exp(-d / 350) * 0.5)   # gleiche Straße weit, andere nur sehr nah
    num += w * math.log(r); den += w
fac_e = np.exp(num / den)
fac_a = np.ones(NA); m_ = AE >= 0; fac_a[m_] = fac_e[AE[m_]]
for a, r in exact.items(): fac_a[a] = r
COMP = COMP * fac_a
pred2 = np.array([COMP[:, o[2]].sum() for o in OBS])
log(f'nach Anpassung: mittlere Abweichung {np.mean(np.abs(pred2 - y) / y) * 100:.0f} % (an den Zählstellen selbst exakt)')

# ---------------- Ausgabe ----------------
def dp(pts, tol=3.0):
    if len(pts) < 3: return pts
    a, b = pts[0], pts[-1]
    ax, ay, bx, by = a[1] * KX, a[0] * KY, b[1] * KX, b[0] * KY
    L = math.hypot(bx - ax, by - ay) or 1e-9
    mi, md = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs((bx - ax) * (ay - pts[i][0] * KY) - (ax - pts[i][1] * KX) * (by - ay)) / L
        if d > md: mi, md = i, d
    return [a, b] if md <= tol else dp(pts[:mi + 1], tol)[:-1] + dp(pts[mi:], tol)
edges = []
tot_e = np.zeros(NE)
mreal = AE >= 0
np.add.at(tot_e, AE[mreal], COMP.sum(0)[mreal])
for e in range(NE):
    if tot_e[e] < 40: continue
    g = dp(EG[e])
    flat = []
    px, py = 0, 0
    for la, lo in g:
        X_, Y_ = round(la * 1e5), round(lo * 1e5)
        flat += [X_ - px, Y_ - py]; px, py = X_, Y_
    dirs = []
    for dr in (0, 1):
        a = np.where((AE == e) & (AD == dr))[0]
        dirs.append([int(round(v)) for v in COMP[:, a[0]]] if len(a) else None)
    edges.append({'g': flat, 'k': CLS[EC[e]][2], 'n': EN[e] or ER[e], 'r': ER[e], 'f': dirs[0], 'b': dirs[1]})
stations = []
for o in OBS:
    s, di, a = o[0], o[1], o[2]
    stations.append({'id': s['id'], 'dir': di, 'mess': round(o[3]), 'roh': int(round(raw[a]))})
meta = {'r2': round(float(1 - np.sum((pred - y) ** 2) / np.sum((y - y.mean()) ** 2)), 3),
        'mape': round(float(np.mean(np.abs(pred - y) / y)) * 100, 1), 'n': len(OBS),
        'faktoren': {n_: round(float(v), 4) for n_, v in zip(names, x)}}
json.dump({'edges': edges, 'prof': prof, 'stations': stations, 'meta': meta}, open(outf, 'w', encoding='utf8'),
          ensure_ascii=False, separators=(',', ':'))
log(f'{len(edges)} Straßenabschnitte geschrieben; Abweichung an Zählstellen im Mittel {meta["mape"]} %, R² {meta["r2"]}')

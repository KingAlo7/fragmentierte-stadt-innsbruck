"""Baut index.html aus vorlage.html und den Datendateien.
Aufruf (im Ordner werkzeuge):  python bauen.py
"""
import json, os
H = os.path.dirname(os.path.abspath(__file__)); R = os.path.dirname(H)
rd = lambda *p: open(os.path.join(*p), encoding='utf8').read()
c = json.loads(rd(H, 'content.json'))
dorf = json.loads(rd(H, 'daten', 'doerfer.json'))
# Flächen: automatisch aus den Daten abgeleitet (masken.py)
c['areas'] = json.loads(rd(H, 'daten', 'flaechen.json'))
# Beschriftung: knapp oberhalb der Hauptfläche jedes Dorfs
lab = {'Scharnitz': [47.333, 11.40], 'Zirl': [47.2835, 11.247], 'Thaur': [47.3005, 11.484], 'Mutters': [47.2265, 11.3790]}
for a in dorf:
    if a['name'] in lab or '(' in a['name']: continue
    la = sum(p[0] for p in a['coords']) / len(a['coords']); lo = sum(p[1] for p in a['coords']) / len(a['coords'])
    lab[a['name']] = [round(la + 0.0048, 4), round(lo, 4)]
J = lambda o: json.dumps(o, ensure_ascii=False, separators=(',', ':'))
data = "const AREAS=" + J(c["areas"]) + ";\nconst AREAS_W=" + rd(H, "daten", "flaechen_wohnen.json") + ";\nconst POINTS=" + J(c['points']) + ";\nconst EXTRA_LABELS=" + J(lab) + ";\nconst BARRIER_INFO=" + J(c['barriers']) + ";\n"
heat = json.loads(rd(H, 'daten', 'heat.json'))
rep = {'__BOUNDARIES__': rd(R, 'boundaries.geojson'), '__LINES__': rd(H, 'lines.geojson'),
       '__HEAT__': J(heat), '__TRAFFIC__': rd(H, 'daten', 'traffic.json'), '__NET__': rd(H, 'daten', 'netz.json'), '__DATA__': data,
       '__SIGMA__': str(heat['sigma_m']), '__OSMDATE__': heat.get('date', ''),
       '__R2__': str(json.loads(rd(H, 'daten', 'netz.json'))['meta']['r2']).replace('.', ',')}
# Flächenwidmung für die Karte (ohne allgemeine Sonderflächen wie Parkplätze/Grünanlagen) + Einkaufszentren-Zonen
from shapely.geometry import shape, Point
Z = json.loads(rd(H, 'daten', 'widmung.geojson'))
GEMN = {v['gkz']: k for k, v in json.loads(rd(H, 'daten', 'gemeinden_statistik.json')).items()}
zf = [f for f in Z['features'] if f['properties']['kat'] != 'sonder']
for f in zf: f['properties']['gname'] = GEMN.get(str(f['properties']['gem']), '')
for f in json.loads(rd(H, 'daten', 'einkaufszentren.geojson'))['features']:
    p = f['properties']
    if p.get('OBJEKT') in ('EKZKZ', 'EKZSR'):
        zf.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {'kat': 'ekz', 'w': p.get('OBJEKTBEZEICHNUNG'), 'f': '', 'gname': GEMN.get(str(p.get('GEMNR')), '')}})
rep['__ZONING__'] = J({'type': 'FeatureCollection', 'features': zf})
s = rd(H, 'vorlage.html')
for k, v in rep.items(): s = s.replace(k, v)
open(os.path.join(R, 'index.html'), 'w', encoding='utf8', newline='\n').write(s)
print('index.html', len(s) // 1024, 'KB')

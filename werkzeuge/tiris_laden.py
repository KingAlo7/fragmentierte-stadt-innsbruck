"""Lädt Ebenen aus dem tiris-FeatureServer (Land Tirol, CC BY 4.0) für das Untersuchungsgebiet als GeoJSON.

Aufruf: python tiris_laden.py <Dienst> <where> <Felder> <ziel.geojson>
  z. B. python tiris_laden.py Landnutzung "OBJEKT LIKE 'LN-S%' OR OBJEKT LIKE 'LN-A%' OR OBJEKT='LN-VF'" OBJEKT,KLASSE,GEMNR,STAND roh/landnutzung.geojson
        python tiris_laden.py Gebaeude 1=1 GEB_HOEHE_MAX,GEB_HOEHE_MEDIAN,GEMNR,STAND roh/gebaeude.geojson
"""
import json, sys, time, urllib.parse, urllib.request
BASE = 'https://services3.arcgis.com/hG7UfxX49PQ8XkXh/arcgis/rest/services/{}/FeatureServer/0/query'
BBOX = {'xmin': 11.235, 'ymin': 47.17, 'xmax': 11.545, 'ymax': 47.34, 'spatialReference': {'wkid': 4326}}
svc, where, fields, out = sys.argv[1:5]

def q(**kw):
    p = dict(where=where, geometry=json.dumps(BBOX), geometryType='esriGeometryEnvelope', inSR=4326,
             spatialRel='esriSpatialRelIntersects', f='json')
    p.update(kw)
    for t in range(5):
        try:
            req = urllib.request.Request(BASE.format(svc), data=urllib.parse.urlencode(p).encode())
            return json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:
            print('Wiederholung', t, e); time.sleep(3)
    raise SystemExit('Abbruch')

ids = sorted(q(returnIdsOnly='true')['objectIds'])
print(svc, len(ids), 'Objekte')
feats = []
STEP = 500
for i in range(0, len(ids), STEP):
    chunk = ids[i:i + STEP]
    r = q(where='1=1', objectIds=','.join(map(str, chunk)), outFields='OBJECTID,' + fields, outSR=4326, f='geojson',
          geometryPrecision=6)
    got = r.get('features', [])
    if len(got) != len(chunk): print(f'\nWarnung: {len(got)} von {len(chunk)} Objekten', end=' ')
    feats += got
    print(len(feats), end=' ', flush=True)
json.dump({'type': 'FeatureCollection', 'features': feats}, open(out, 'w', encoding='utf8'), ensure_ascii=False)
print('\n->', out, len(feats))

"""Amtliche Flächenwidmung (Land Tirol, tiris, CC BY 4.0) aufbereiten.

Aufruf: python widmung.py flw_0.geojson flw_2000.geojson ... daten/widmung.geojson
Quelle: https://services3.arcgis.com/hG7UfxX49PQ8XkXh/arcgis/rest/services/FLW_Flaechenwidmung/FeatureServer
Jede Widmungsfläche erhält eine vereinfachte Klasse (kat) und ihre Bedeutung für die Kategorien der Karte.
"""
import json, sys, re
from shapely.geometry import shape, mapping

def klasse(w, fest):
    w = w or ''; f = (fest or '').lower()
    if w.startswith('Gewerbe- u. Industriegebiet'): return 'gewerbe'
    if 'Einkaufszentrum' in w or 'Handelsbetrieb' in w or 'kundenfläche' in f or 'betriebstyp' in f: return 'handel'
    if w.startswith('Kerngebiet'): return 'kern'
    if w.startswith('Allgemeines Mischgebiet') or w.startswith('Tourismusgebiet'): return 'misch'
    if w.startswith('Gemischtes Wohngebiet'): return 'wohnmisch'
    if 'geförderten Wohnbau' in w: return 'gefwohn'
    if w.startswith('Wohngebiet'): return 'wohn'
    if w.startswith('Landwirtschaftliches Mischgebiet'): return 'dorf'
    if w.startswith(('Sonderfläche', 'Vorbehaltsfläche')):
        if re.search(r'schul|bildung|universit|kindergarten|studierend|hochschul|forschung|internat', f): return 'bildung'
        if re.search(r'lager|großhandel|gewerb|betrieb|bauhof|kraftwerk|recycling|werkstät|kompost|wirtschaftsgeb|klärwerk|umspann', f): return 'betrieb'
        if re.search(r'grünanlage|grünfläche|grüngürtel|park|sport|spielplatz|promenade|kleingärt|kleingarten|schrebergarten|golf|schipiste|liftstation|tennis|reitplatz|bad|freibad|schwimm|camping|freizeit|erholung|eislauf|kletter|rodel|fischteich|zoo', f): return 'freizeit'
        if re.search(r'hotel|gasthof|gasthaus|beherberg', f) or 'Beherbergung' in w: return 'gast'
        return 'sonder'
    return 'sonst'

feats = []
for fn in sys.argv[1:-1]:
    for ft in json.load(open(fn, encoding='utf8'))['features']:
        p = ft['properties']
        try: g = shape(ft['geometry']).buffer(0).simplify(0.000015)
        except Exception: continue
        if g.is_empty: continue
        k = klasse(p.get('WIDMUNG', p.get('w')), p.get('FESTLEGUNG', p.get('f')))
        geo = mapping(g)
        def rnd(c):
            return [rnd(x) for x in c] if isinstance(c[0], (list, tuple)) else [round(c[0], 6), round(c[1], 6)]
        geo['coordinates'] = rnd(geo['coordinates'])
        feats.append({'type': 'Feature', 'properties': {'kat': k, 'w': p.get('WIDMUNG', p.get('w')), 'f': p.get('FESTLEGUNG', p.get('f')) or '', 'gem': p.get('GEMNR', p.get('gem'))},
                      'geometry': geo})
json.dump({'type': 'FeatureCollection', 'features': feats}, open(sys.argv[-1], 'w', encoding='utf8'), ensure_ascii=False, separators=(',', ':'))
from collections import Counter
print(len(feats), Counter(f['properties']['kat'] for f in feats))

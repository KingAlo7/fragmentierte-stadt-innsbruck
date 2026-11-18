"""Extrahiert Gebäude, POIs und Landnutzung aus einem OSM-PBF-Auszug (z. B. BBBike Innsbruck)
in Overpass-ähnliches JSON für heat.py.   Aufruf: python osm2json.py auszug.osm.pbf zielordner
"""
import osmium, json, sys, os
S, W, N, E = 47.170, 11.235, 47.340, 11.545
LU = {'retail', 'commercial', 'industrial', 'residential', 'education', 'railway', 'recreation_ground', 'allotments', 'cemetery'}
LEIS = {'park', 'garden', 'playground', 'pitch', 'sports_centre', 'stadium', 'swimming_pool', 'water_park', 'golf_course',
        'ice_rink', 'track', 'fitness_centre', 'miniature_golf', 'dog_park', 'horse_riding', 'bathing_place', 'climbing'}
TOUR = {'zoo', 'theme_park', 'camp_site', 'picnic_site', 'viewpoint'}
AM_AREA = {'university', 'college', 'school', 'hospital'}
POI_AM = {'university', 'college', 'school', 'kindergarten', 'research_institute', 'library', 'marketplace',
          'restaurant', 'cafe', 'fast_food', 'bank', 'pharmacy', 'cinema'}
inb = lambda la, lo: S <= la <= N and W <= lo <= E
def ispoi(t):
    return t.get('leisure') in LEIS or t.get('tourism') in TOUR or 'shop' in t or t.get('amenity') in POI_AM or 'office' in t or 'craft' in t or t.get('man_made') == 'works'

class H(osmium.SimpleHandler):
    def __init__(s):
        super().__init__(); s.bld = []; s.poi = []; s.lu = []
    def node(s, n):
        t = {k.k: k.v for k in n.tags}
        if t and ispoi(t) and n.location.valid() and inb(n.location.lat, n.location.lon):
            s.poi.append({'type': 'node', 'lat': n.location.lat, 'lon': n.location.lon, 'tags': t})
    def area(s, a):
        t = {k.k: k.v for k in a.tags}
        isb = 'building' in t; isl = t.get('landuse') in LU or t.get('amenity') in AM_AREA or t.get('aeroway') == 'aerodrome' or t.get('leisure') in LEIS or t.get('tourism') in TOUR
        isp = ispoi(t)
        if not (isb or isl or isp): return
        try:
            rings = [[{'lat': nd.lat, 'lon': nd.lon} for nd in r] for r in a.outer_rings()]
        except Exception:
            return
        rings = [r for r in rings if len(r) > 3]
        if not rings: return
        la = sum(p['lat'] for p in rings[0]) / len(rings[0]); lo = sum(p['lon'] for p in rings[0]) / len(rings[0])
        if not inb(la, lo): return
        if isp: s.poi.append({'type': 'way', 'center': {'lat': la, 'lon': lo}, 'tags': t})
        for r in rings:
            el = {'type': 'way', 'tags': t, 'geometry': r}
            if isb: s.bld.append(el)
            if isl: s.lu.append(el)

h = H(); h.apply_file(sys.argv[1], locations=True)
meta = {'osm3s': {'timestamp_osm_base': '2026-11-14T16:45:47Z', 'source': 'BBBike-Auszug Innsbruck'}}
for n in ('bld', 'poi', 'lu'):
    json.dump(dict(meta, elements=getattr(h, n)), open(os.path.join(sys.argv[2], n + '.json'), 'w', encoding='utf8'))
    print(n, len(getattr(h, n)))

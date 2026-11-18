"""Ortsteil-/Ortsnamen (place=*) aus dem OSM-Auszug. Aufruf: python orte.py auszug.osm.pbf daten/orte.json"""
import osmium, json, sys
R = {'city': 0, 'town': 1, 'village': 2, 'suburb': 3, 'quarter': 4, 'neighbourhood': 5, 'hamlet': 6, 'isolated_dwelling': 9, 'locality': 8}
out = []
class H(osmium.SimpleHandler):
    def node(s, n):
        p = n.tags.get('place'); nm = n.tags.get('name')
        if p in R and nm and 47.17 < n.location.lat < 47.34 and 11.23 < n.location.lon < 11.55:
            out.append({'name': nm, 'place': p, 'rank': R[p], 'lat': n.location.lat, 'lon': n.location.lon})
H().apply_file(sys.argv[1])
json.dump(out, open(sys.argv[2], 'w', encoding='utf8'), ensure_ascii=False)
print(len(out), 'Orte')

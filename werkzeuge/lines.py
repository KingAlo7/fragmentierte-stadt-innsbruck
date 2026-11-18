import json,sys,math,collections
d=json.load(open(sys.argv[1],encoding='utf8'))
def dp(pts,eps):
    if len(pts)<3: return pts
    a,b=pts[0],pts[-1]; dm=0; idx=0
    for i in range(1,len(pts)-1):
        p=pts[i]; dx,dy=b[0]-a[0],b[1]-a[1]; L=dx*dx+dy*dy
        t=0 if L==0 else max(0,min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/L))
        dist=math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy)
        if dist>dm: dm,idx=dist,i
    return dp(pts[:idx+1],eps)[:-1]+dp(pts[idx:],eps) if dm>eps else [a,b]
def merge(ways):
    ways=[w[:] for w in ways]; out=[]
    while ways:
        r=ways.pop(0); ch=True
        while ch:
            ch=False
            for i,w in enumerate(ways):
                if w[0]==r[-1]: r+=w[1:]
                elif w[-1]==r[0]: r=w[:-1]+r
                elif w[-1]==r[-1]: r+=w[::-1][1:]
                elif w[0]==r[0]: r=w[::-1][:-1]+r
                else: continue
                ways.pop(i); ch=True; break
        out.append(r)
    return out
groups=collections.defaultdict(list); pois=[]
for e in d['elements']:
    t=e.get('tags',{})
    if e['type']=='way' and 'geometry' in e and (t.get('highway')=='motorway' or t.get('waterway')=='river' or t.get('railway')=='rail'):
        g=[(round(p['lon'],5),round(p['lat'],5)) for p in e['geometry']]
        if t.get('highway')=='motorway':
            ref=t.get('ref','?').split(';')[0]
            if ref in('A12','A13'): groups[ref].append(g)
        elif t.get('waterway'): groups['inn'].append(g)
        else: groups['rail:'+t.get('name','')].append(g)
    else:
        c=e.get('center') or {'lat':e.get('lat'),'lon':e.get('lon')}
        pois.append((t.get('name'),{k:v for k,v in t.items() if k in('shop','amenity','office','aerial','aerialway','railway','aeroway','building','addr:street')},c))
print({k:len(v) for k,v in groups.items()})
for p in pois: print(p)
json.dump({k:v for k,v in groups.items()},open(sys.argv[2],'w'))

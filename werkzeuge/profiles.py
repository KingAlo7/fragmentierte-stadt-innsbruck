import openpyxl,sys,json,datetime
IDS={'8851','8852','8853','8881','8882','8883','8884','8885','8888','8157','8155','8246','8213','8208','8158','8237','8238','8261'}
wb=openpyxl.load_workbook(sys.argv[1],read_only=True); ws=wb.worksheets[0]
rows=list(ws.iter_rows(values_only=True)); h0,h1,h2=rows[0],rows[1],rows[2]
data=[r for r in rows[3:] if r[0] and str(r[0])[:2].isdigit()]
out={}
for c in range(1,len(h0)):
    if h1[c]!='KFZ' or not h0[c]: continue
    sid=h0[c].split(' - ')[0].strip()
    if sid not in IDS: continue
    wd=[[] for _ in range(24)]; we=[[] for _ in range(24)]
    for r in data:
        v=r[c]
        if not isinstance(v,(int,float)): continue
        d=datetime.datetime.strptime(r[0],'%d.%m.%Y %H:%M')
        (wd if d.weekday()<5 else we)[d.hour].append(v)
    m=lambda L:[round(sum(x)/len(x),1) if x else 0 for x in L]
    o=out.setdefault(sid,{'name':h0[c].split(' - ',1)[1],'dirs':[]})
    o['dirs'].append({'dir':h2[c].split(' - ',1)[1],'werktag':m(wd),'wochenende':m(we)})
json.dump(out,open(sys.argv[2],'w',encoding='utf8'),ensure_ascii=False,indent=0)
for k,v in out.items(): print(k,v['name'],[ (d['dir'],round(sum(d['werktag']))) for d in v['dirs']])

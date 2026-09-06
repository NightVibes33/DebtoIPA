#!/usr/bin/env python3
import json,re

SRC='source.json'
OUT='sidestore-source.json'
OUT_URL='https://raw.githubusercontent.com/NightVibes33/DebtoIPA/flekstore-alt-source/sidestore-source.json'

def safe_version(v):
    s=str(v or '').strip()
    m=re.match(r'^(\d+(?:\.\d+)*)', s)
    return m.group(1) if m else '1.0'

def clip(s,n):
    return str(s or '')[:n]

src=json.load(open(SRC,encoding='utf-8'))
apps=[]
for a in src.get('apps',[]):
    versions=[]
    for v in a.get('versions') or []:
        versions.append({
            'version': safe_version(v.get('version')),
            'date': str(v.get('date') or '2026-01-01'),
            'downloadURL': str(v.get('downloadURL') or a.get('downloadURL') or ''),
            'size': int(v.get('size') or a.get('size') or 0),
            'localizedDescription': clip(v.get('localizedDescription') or a.get('localizedDescription'),180),
        })
    if not versions:
        continue
    latest=versions[0]
    app={
        'name': clip(a.get('name'),120),
        'bundleIdentifier': str(a.get('bundleIdentifier')),
        'developerName': clip(a.get('developerName') or 'FlekSt0re',80),
        'localizedDescription': clip(a.get('localizedDescription') or 'FlekSt0re catalog app',420),
        'iconURL': str(a.get('iconURL') or 'https://flekstore.com/favicon.ico'),
        'downloadURL': latest['downloadURL'],
        'versions': versions,
    }
    subtitle=clip(a.get('subtitle'),90)
    if subtitle: app['subtitle']=subtitle
    tint=a.get('tintColor')
    if isinstance(tint,str) and re.fullmatch(r'#?[0-9A-Fa-f]{6}',tint): app['tintColor']=tint
    apps.append(app)

out={
    'name':'FlekSt0re Lib Mirror (SideStore Safe v3)',
    'identifier':'com.nightvibes33.flekstorelib.sidestore.v3',
    'sourceURL':OUT_URL,
    'apps':apps,
}
json.dump(out,open(OUT,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
open(OUT,'a',encoding='utf-8').write('\n')
print('WROTE',OUT,'APPS',len(apps))

#!/usr/bin/env python3
import hashlib
import json
import re
from collections import Counter

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
raw_apps=src.get('apps',[])
counts=Counter(str(a.get('bundleIdentifier') or '') for a in raw_apps)
apps=[]
for a in raw_apps:
    versions=[]
    for v in a.get('versions') or []:
        item={
            'version': safe_version(v.get('version')),
            'date': str(v.get('date') or '2026-01-01'),
            'downloadURL': str(v.get('downloadURL') or a.get('downloadURL') or ''),
            'size': int(v.get('size') or a.get('size') or 0),
            'localizedDescription': clip(v.get('localizedDescription') or a.get('localizedDescription'),180),
        }
        min_os=str(v.get('minOSVersion') or '').strip()
        if min_os:
            item['minOSVersion']=min_os
        versions.append(item)
    if not versions:
        continue
    latest=versions[0]
    real_bundle=str(a.get('bundleIdentifier') or '').strip()
    bundle=real_bundle
    # SideStore uses bundleIdentifier as the listing identity. FlekSt0re carries
    # several different tweaked apps that intentionally share the same embedded
    # CFBundleIdentifier (Instagram, YouTube, Spotify, Pokemon Go, etc.). Preserve
    # every listing by assigning a deterministic source-only identity to collision
    # groups. The IPA itself retains its embedded bundle ID when downloaded.
    if counts.get(real_bundle,0)>1:
        seed=(real_bundle+'\0'+str(a.get('name'))+'\0'+latest['downloadURL']).encode('utf-8')
        suffix=hashlib.sha1(seed).hexdigest()[:12]
        bundle=f'com.nightvibes33.flekvariant.{suffix}'
    app={
        'name': clip(a.get('name'),120),
        'bundleIdentifier': bundle,
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

ids=[a['bundleIdentifier'] for a in apps]
assert len(ids)==len(set(ids)), 'SideStore feed still contains duplicate bundle identifiers'

out={
    'name':'FlekSt0re Lib Mirror (SideStore Safe v4)',
    'identifier':'com.nightvibes33.flekstorelib.sidestore.v4',
    'sourceURL':OUT_URL,
    'apps':apps,
}
json.dump(out,open(OUT,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
open(OUT,'a',encoding='utf-8').write('\n')
print('WROTE',OUT,'APPS',len(apps),'UNIQUE_IDS',len(set(ids)))

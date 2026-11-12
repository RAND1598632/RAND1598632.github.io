# -*- coding: utf-8 -*-
"""覆盖率报表：哪些专辑的曲目还没接上讲解、哪些轨没匹配到作品"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import build as B

inv = json.load(io.open(os.path.join(B.DATA, 'inventory.json'), encoding='utf-8'))
kn_albums, works, works_map, loose, conflicts = B.load_knowledge()

rows = []
for al in inv['albums']:
    if not al['tracks']:
        continue
    kn = kn_albums.get(al['name']) or {}
    pref = B.composer_key(kn.get('composer', ''))
    tot = len(al['tracks'])
    hit, miss = 0, []
    for g in B.group_tracks(works, al['tracks'], kn.get('track_works'), works_map, pref):
        if g['work']:
            hit += len(g['tracks'])
        else:
            miss.extend(t.get('title') for t in g['tracks'])
    rows.append((hit / tot, tot, hit, al['name'], miss[:4], bool(kn.get('version_notes'))))

rows.sort(key=lambda r: (r[0], -r[1]))
out = []
w = out.append
w(f'专辑 {len(rows)} 张；作品 {len(works)} 部；重复条目 {len(conflicts)}')
w('\n## 覆盖率最低的 30 张')
for r in rows[:30]:
    w(f'{r[0] * 100:5.1f}%  {r[2]:>4}/{r[1]:<4} {"有讲解" if r[5] else "无讲解"}  {r[3][:58]}')
    for m in r[4]:
        w(f'        未匹配: {m[:80]}')
w('\n## 无讲解的专辑')
for al in inv['albums']:
    if al['name'] not in kn_albums:
        w(f'  {al["name"]}  ({al["stats"]["n_tracks"]} 轨)')
w('\n## 全部专辑覆盖率')
for r in sorted(rows, key=lambda r: r[3]):
    w(f'{r[0] * 100:5.1f}%  {r[2]:>4}/{r[1]:<4}  {r[3][:64]}')

txt = '\n'.join(out)
io.open(os.path.join(B.DATA, 'coverage.md'), 'w', encoding='utf-8').write(txt)
print('WROTE coverage.md')

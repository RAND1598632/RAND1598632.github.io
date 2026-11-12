# -*- coding: utf-8 -*-
"""审计：作品匹配结果、乐章对齐情况、覆盖率"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import build as B

ROOT = B.ROOT
inv = json.load(io.open(os.path.join(B.DATA, 'inventory.json'), encoding='utf-8'))
kn_albums, works, works_map, loose, conflicts = B.load_knowledge()
out = []
w = out.append
w(f'作品条目 {len(works)}，专辑条目 {len(kn_albums)}')
for wk in works:
    hits = []
    for al in inv['albums']:
        for g in B.group_tracks(works, al['tracks']):
            if g['work'] is wk:
                for t in g['tracks']:
                    hits.append((al['name'][:38], t.get('no'), (t.get('title') or '')[:60],
                                 (t.get('_mv') or {}).get('n')))
    w(f"\n### {wk['_id']}  {wk.get('title')}  命中 {len(hits)} 轨，乐章 {len(wk['_mv'])}")
    for h in hits[:12]:
        w(f"    [{h[0]}] {h[1]:>3} mv={h[3]}  {h[2]}")
    if len(hits) > 12:
        w(f"    ... 另有 {len(hits) - 12} 轨")

# 未匹配到任何作品的专辑（检查是否漏配）
w('\n## 完全没匹配到作品的专辑')
for al in inv['albums']:
    if not al['tracks']:
        continue
    ok = sum(1 for g in B.group_tracks(works, al['tracks']) if g['work'] for t in g['tracks'])
    if ok == 0:
        w(f"  {al['name']}  ({al['stats']['n_tracks']} 轨)")

# 可疑匹配：作品作曲家与专辑作曲家对不上
w('\n## 可疑匹配（作品作曲家 vs 专辑作曲家）')
susp = []
for al in inv['albums']:
    kn = kn_albums.get(al['name']) or {}
    acomp = (kn.get('composer') or '').lower()
    if not acomp:
        continue
    for g in B.group_tracks(works, al['tracks']):
        wk = g['work']
        if not wk:
            continue
        wcomp = (wk.get('composer') or '').lower()
        if not wcomp:
            continue
        # 取作曲家名的英文/中文词根做交集
        import re as _re
        aw = set(_re.findall(r'[a-z]{4,}', acomp)) | set(_re.findall(r'[\u4e00-\u9fff]{2,}', acomp))
        ww = set(_re.findall(r'[a-z]{4,}', wcomp)) | set(_re.findall(r'[\u4e00-\u9fff]{2,}', wcomp))
        if not (aw & ww):
            susp.append((al['name'], wk['_id'], len(g['tracks'])))
for x in susp[:60]:
    w(f'  {x[0][:52]}  ←  {x[1]}  ({x[2]} 轨)')
if not susp:
    w('  （无）')

# 弱匹配：在大专辑里只命中 1 轨、且作曲家对不上 / 无体裁佐证
w('\n## 弱匹配（大专辑里只命中 1 轨，重点复核）')
weak = []
for al in inv['albums']:
    kn = kn_albums.get(al['name']) or {}
    pref = B.composer_key(kn.get('composer', ''))
    ntr = al['stats']['n_tracks']
    if ntr < 10:
        continue
    cnt = {}
    for g in B.group_tracks(works, al['tracks'], kn.get('track_works'), works_map, pref):
        if g['work']:
            cnt[g['work']['_id']] = cnt.get(g['work']['_id'], 0) + len(g['tracks'])
    for wid, c in cnt.items():
        wk = works_map[wid]
        if c <= 1:
            weak.append((al['name'], ntr, wid, wk.get('title'), c))
for x in weak:
    w(f'  {x[0][:46]} ({x[1]} 轨) ← {x[2]} {x[3]}')
if not weak:
    w('  （无）')

# 专辑里命中作品数异常多的
w('\n## 每张专辑命中情况')
for al in inv['albums']:
    if not al['tracks']:
        continue
    kn = kn_albums.get(al['name']) or {}
    pref = B.composer_key(kn.get('composer', ''))
    ids = []
    for g in B.group_tracks(works, al['tracks'], kn.get('track_works'), works_map, pref):
        if g['work']:
            ids.append((g['work']['_id'], len(g['tracks'])))
    if ids:
        w(f'  {al["stats"]["n_tracks"]:>4} 轨 / 命中 {sum(c for _, c in ids):>4} → {al["name"][:48]}'
          f'  [{", ".join(f"{i}×{c}" for i, c in ids)[:110]}]')

txt = '\n'.join(out)
io.open(os.path.join(B.DATA, 'audit.md'), 'w', encoding='utf-8').write(txt)
print('WROTE audit.md', len(txt))

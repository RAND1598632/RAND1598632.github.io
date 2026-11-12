# -*- coding: utf-8 -*-
"""体检：打印结构化结果，供人工核对。"""
import json
import os
import sys

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = ''
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def fmt(sec):
    if not sec:
        return '--:--'
    sec = int(sec)
    return f'{sec // 60}:{sec % 60:02d}'


def main():
    d = json.load(open(os.path.join(DATA, 'inventory.json'), encoding='utf-8'))
    out = []
    w = out.append
    for al in d['albums']:
        st = al['stats']
        w(f"\n### {al['name']}  [{al['kind']}]")
        w(f"音频{st['n_audio']} 轨{st['n_tracks']} 碟{st['n_discs']} 时长{fmt(st['duration'])} "
          f"规格{dict(list(st['specs'].items())[:5])}")
        for dc in al['discs']:
            w(f"  - 碟: {dc['label']}" + (' [镜像]' if dc.get('image') else '') + f" 轨{len(dc['tracks'])}")
            for t in dc['tracks'][:4]:
                w(f"      {str(t.get('no')):>3} {fmt(t.get('duration'))} {t.get('spec','')} | {t.get('title','')} | {t.get('performer','')}")
            if len(dc['tracks']) > 4:
                w(f"      ... (+{len(dc['tracks']) - 4})")
        if al['junk']:
            w(f"  杂项{len(al['junk'])}: " + ', '.join(x['name'] for x in al['junk'][:6]))
    w('\n## loose')
    for x in d['loose']:
        w(f"  {x['name']} {x.get('type')} {(x.get('tags') or {}).get('spec','')} {fmt((x.get('tags') or {}).get('duration'))}")
    txt = '\n'.join(out)
    open(os.path.join(DATA, 'check.md'), 'w', encoding='utf-8').write(txt)
    print('WROTE check.md', len(txt))


if __name__ == '__main__':
    main()

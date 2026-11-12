# -*- coding: utf-8 -*-
"""从 inventory.json 生成一份便于人工/模型阅读的摘要 digest.md"""
import json
import os
import sys
from collections import OrderedDict

ROOT = ''
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')


def fmt_dur(sec):
    if not sec:
        return '--'
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def fmt_size(b):
    for u in ('B', 'KB', 'MB', 'GB'):
        if b < 1024:
            return f'{b:.0f}{u}'
        b /= 1024
    return f'{b:.1f}TB'


def main():
    data = json.load(open(os.path.join(DATA, 'inventory.json'), encoding='utf-8'))
    out = []
    w = out.append
    w('# 音乐库摘要\n')
    tot_audio = sum(len(a['audio']) for a in data['albums'])
    tot_size = sum(x['size'] for a in data['albums'] for x in a['audio'] + a['images'] + a['videos'])
    w(f'顶层条目 {len(data["albums"])} 个，音频文件 {tot_audio} 个，含影像/镜像总占用 {fmt_size(tot_size)}\n')
    for i, al in enumerate(data['albums'], 1):
        audio = al['audio']
        imgs = al['images']
        vids = al['videos']
        cues = al['cue_sheets']
        dur = sum((a.get('tags') or {}).get('duration') or 0 for a in audio)
        size = sum(x['size'] for x in audio + imgs + vids)
        dirs = set()
        for a in audio:
            d = os.path.dirname(a['path'])
            dirs.add(d)
        w(f'\n## [{i}] {al["name"]}')
        w(f'- 音频 {len(audio)} 个 / 时长 {fmt_dur(dur)} / 占用 {fmt_size(size)} / 子目录 {len(dirs)}'
          + (f' / 镜像 {len(imgs)}' if imgs else '') + (f' / 视频 {len(vids)}' if vids else '')
          + (f' / CUE {len(cues)}' if cues else ''))
        # 找“专辑”级别的标签
        albs = OrderedDict()
        for a in audio:
            t = a.get('tags') or {}
            k = (t.get('album') or '').strip()
            if k:
                albs[k] = albs.get(k, 0) + 1
        if albs:
            top = list(albs.items())[:4]
            w('- 专辑标签: ' + '; '.join(f'{k} ({v})' for k, v in top))
        junk = al['junk']
        if junk:
            w(f'- 残留备份/杂项: {len(junk)} 个 (如 {", ".join(j["name"] for j in junk[:4])})')
        # track 列表
        if cues:
            for cs in cues:
                w(f'- CUE: {os.path.basename(cs["cue_path"])} -> {cs["file"]} ({len(cs["tracks"])} 轨)'
                  + (f' [{cs["title"]}]' if cs['title'] else ''))
                for t in cs['tracks'][:3]:
                    w(f'    - {t["no"]:02d} {t["index"]} {t["title"]}')
                if len(cs['tracks']) > 3:
                    w('    - ...')
        elif audio:
            named = [a for a in audio if (a.get('tags') or {}).get('title')]
            show = named if named else audio
            for a in show[:6]:
                t = a.get('tags') or {}
                title = t.get('title') or a['name']
                extra = ' | '.join(x for x in [t.get('composer'), t.get('artist') or t.get('performer'), t.get('date')] if x)
                w(f'    - {fmt_dur(t.get("duration"))}  {title}' + (f'   [{extra}]' if extra else ''))
            if len(show) > 6:
                w(f'    - ...共 {len(audio)} 轨')
    w('\n## 散落文件')
    for a in data['loose']:
        t = a.get('tags') or {}
        w(f'- {a["name"]} ({fmt_size(a["size"])}) {t.get("title","")}')
    txt = '\n'.join(out)
    p = os.path.join(DATA, 'digest.md')
    open(p, 'w', encoding='utf-8').write(txt)
    print('WROTE', p, len(txt), 'chars')


if __name__ == '__main__':
    main()

# -*- coding: utf-8 -*-
"""
扫描音乐库 -> inventory.json（结构化清单，供 build.py 渲染）。

做三件事：
 1) 只读文件头拿标签/规格（mutagen，不解码音频）；
 2) 解析 CUE：单镜像（1 个 FILE 多 TRACK）与自制 CUE（多 FILE 各 1 TRACK）分开处理；
 3) 归并成「专辑 -> 碟 -> 轨」的结构，附带统计与异常清单。

用法: python scan.py [--root <库根>]
"""
import argparse
import json
import os
import re
import sys
import time

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

AUDIO_EXT = {'.flac', '.wav', '.ape', '.dsf', '.dff', '.mp3', '.m4a', '.wv', '.aif', '.aiff', '.ogg', '.wma', '.tta'}
ISO_EXT = {'.iso'}
VIDEO_EXT = {'.ts', '.vob', '.m2ts', '.mkv', '.mp4', '.avi', '.mov', '.mpls', '.clpi'}
ART_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.webp'}
DOC_EXT = {'.pdf', '.txt', '.log', '.m3u', '.accurip', '.md5', '.sfv', '.sha', '.xml', '.lrc', '.nfo', '.db', '.torrent'}
JUNK_RE = re.compile(r'(\.bak|\.bak-[\w-]+|~|\.xdelta|\.sig|\.crt|\.rar|\.zip)$', re.I)

CYR_RE = re.compile(r'[\u0400-\u04FF]')
CJK_RE = re.compile(r'[\u4e00-\u9FFF]')


def natkey(t):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r'(\d+)', t or '')]


def s(v):
    if v is None:
        return ''
    if isinstance(v, (list, tuple)):
        v = v[0] if v else ''
    return str(v).strip()


# ---------------------------------------------------------------- 标签
def spec_label(ext, sample_rate, bits, channels, codec):
    if not sample_rate:
        return ext.upper().lstrip('.')
    if ext in ('.dsf', '.dff'):
        mult = round(sample_rate / 44100.0)
        return f'DSD{64 * mult}' if mult in (1, 2, 4, 8) else f'DSD {sample_rate}'
    kb = sample_rate / 1000.0
    kb_s = f'{kb:g}kHz'
    b = f'{bits}bit' if bits else ''
    ch = ' 单声道' if channels == 1 else (' 立体声' if channels == 2 else (f' {channels}ch' if channels else ''))
    name = {'.flac': 'FLAC', '.wav': 'WAV', '.ape': 'APE', '.mp3': 'MP3', '.m4a': 'M4A',
            '.wv': 'WV', '.aif': 'AIFF', '.aiff': 'AIFF'}.get(ext, codec or ext.upper().lstrip('.'))
    return f'{name} {b}/{kb_s}{ch}'.replace(' /', '/')


def read_tags(path):
    out = {'duration': None, 'sample_rate': None, 'bits': None, 'channels': None, 'codec': ''}
    ext = os.path.splitext(path)[1].lower()
    try:
        import mutagen
        mf = mutagen.File(path)
        if mf is None:
            return out
        info = getattr(mf, 'info', None)
        if info is not None:
            out['duration'] = round(float(getattr(info, 'length', 0) or 0), 2)
            out['sample_rate'] = getattr(info, 'sample_rate', None)
            out['channels'] = getattr(info, 'channels', None)
            out['bits'] = getattr(info, 'bits_per_sample', None)
            out['codec'] = type(mf).__name__
        if ext in ('.dsf', '.dff'):
            out['bits'] = 1
        tags = mf.tags
        norm = {}
        if tags is not None:
            try:
                for k, v in tags.items():
                    norm[str(k).lower()] = s(v)
            except Exception:
                pass
        for k in ('title', 'artist', 'album', 'albumartist', 'composer', 'conductor',
                  'performer', 'date', 'year', 'tracknumber', 'discnumber', 'genre',
                  'description', 'comment', 'discsubtitle', 'work', 'orchestra', 'ensemble',
                  'lyricist'):
            if norm.get(k):
                out[k] = norm[k]
        if not out.get('year') and out.get('date'):
            mt = re.search(r'(\d{4})', out['date'])
            if mt:
                out['year'] = mt.group(1)
        for k in ('tracknumber', 'discnumber'):
            if out.get(k):
                mt = re.match(r'\s*(\d+)', out[k])
                out[k] = int(mt.group(1)) if mt else None
    except Exception as e:
        out['error'] = f'{type(e).__name__}: {e}'
    out['spec'] = spec_label(ext, out.get('sample_rate'), out.get('bits'), out.get('channels'), out.get('codec'))
    return out


# ---------------------------------------------------------------- CUE
def decode_text(raw, hint=''):
    encs = ['utf-8-sig', 'utf-8']
    if CYR_RE.search(hint):
        encs += ['cp1251', 'koi8-r']
    if CJK_RE.search(hint):
        encs += ['gb18030', 'big5']
    encs += ['gb18030', 'cp1251', 'cp1252', 'latin-1']
    for e in encs:
        try:
            t = raw.decode(e)
            if t.count('\ufffd') == 0:
                return t
        except Exception:
            continue
    return raw.decode('utf-8', 'replace')


def parse_cue(path, hint=''):
    """返回 {'title','performer','blocks':[{'file','tracks':[{no,title,performer,index}]}],'comment'}"""
    try:
        raw = open(path, 'rb').read()
    except Exception:
        return None
    text = decode_text(raw, hint)
    disc_title, disc_perf, comment = '', '', ''
    blocks, cur_block, cur_tr = [], None, None
    for ln in text.splitlines():
        t = ln.strip()
        if not t:
            continue
        m = re.match(r'^REM\s+(.*)$', t, re.I)
        if m:
            if m.group(1).upper().startswith('COMMENT'):
                comment = m.group(1)[7:].strip().strip('"')
            continue
        m = re.match(r'^FILE\s+"?([^"]+?)"?\s+\w+$', t, re.I)
        if m:
            cur_block = {'file': m.group(1).strip(), 'tracks': []}
            blocks.append(cur_block)
            cur_tr = None
            continue
        m = re.match(r'^TRACK\s+(\d+)', t, re.I)
        if m:
            if cur_block is None:
                cur_block = {'file': '', 'tracks': []}
                blocks.append(cur_block)
            cur_tr = {'no': int(m.group(1)), 'title': '', 'performer': '', 'index': ''}
            cur_block['tracks'].append(cur_tr)
            continue
        m = re.match(r'^TITLE\s+"?(.*?)"?$', t, re.I)
        if m:
            if cur_tr is not None:
                cur_tr['title'] = m.group(1).strip()
            else:
                disc_title = m.group(1).strip()
            continue
        m = re.match(r'^PERFORMER\s+"?(.*?)"?$', t, re.I)
        if m:
            if cur_tr is not None:
                cur_tr['performer'] = m.group(1).strip()
            else:
                disc_perf = m.group(1).strip()
            continue
        m = re.match(r'^INDEX\s+01\s+(\d+:\d+:\d+)', t, re.I)
        if m and cur_tr is not None:
            cur_tr['index'] = m.group(1).strip()
            continue
    return {'title': disc_title, 'performer': disc_perf, 'comment': comment, 'blocks': blocks}


# ---------------------------------------------------------------- 目录遍历
def collect(album_dir, root):
    buckets = {'audio': [], 'cue': [], 'iso': [], 'video': [], 'art': [], 'doc': [], 'junk': []}
    for dirpath, dirnames, filenames in os.walk(album_dir):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith('__'))
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            rel = os.path.relpath(full, root)
            rel_dir = os.path.relpath(dirpath, root)
            try:
                st = os.stat(full)
                size, mtime = st.st_size, int(st.st_mtime)
            except Exception:
                size, mtime = 0, 0
            ent = {'path': rel, 'dir': rel_dir, 'name': fn, 'size': size, 'mtime': mtime}
            if JUNK_RE.search(fn):
                buckets['junk'].append(ent)
            elif ext in AUDIO_EXT:
                buckets['audio'].append(ent)
            elif ext == '.cue':
                buckets['cue'].append(ent)
            elif ext in ISO_EXT:
                buckets['iso'].append(ent)
            elif ext in VIDEO_EXT:
                buckets['video'].append(ent)
            elif ext in ART_EXT:
                buckets['art'].append(ent)
            elif ext in DOC_EXT:
                buckets['doc'].append(ent)
    return buckets


def cue_seconds(ix):
    try:
        mm, ss, ff = ix.split(':')
        return int(mm) * 60 + int(ss) + int(ff) / 75.0
    except Exception:
        return None


def probe_media(path):
    """用 ffprobe 读影像/蓝光流的时长与音轨规格（只读头，快）"""
    import subprocess
    out = {}
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'format=duration:stream=codec_name,codec_type,sample_rate,channels,bits_per_raw_sample',
                            '-of', 'json', path],
                           capture_output=True, timeout=90)
        import json as _json
        d = _json.loads(p.stdout.decode('utf-8', 'replace') or '{}')
        fmt = d.get('format', {})
        if fmt.get('duration'):
            out['duration'] = round(float(fmt['duration']), 1)
        auds = []
        for st in d.get('streams', []):
            if st.get('codec_type') != 'audio':
                continue
            cn = st.get('codec_name', '')
            sr = st.get('sample_rate')
            ch = st.get('channels')
            bits = st.get('bits_per_raw_sample')
            name = {'dts': 'DTS', 'pcm_bluray': 'LPCM', 'pcm_s16le': 'PCM', 'pcm_s24le': 'PCM',
                    'truehd': 'Dolby TrueHD', 'ac3': 'Dolby Digital', 'eac3': 'Dolby Digital+',
                    'flac': 'FLAC', 'alac': 'ALAC', 'aac': 'AAC', 'mp3': 'MP3'}.get(cn, cn.upper())
            lab = name
            if bits:
                lab += f' {bits}bit'
            if sr:
                lab += f'/{int(sr) / 1000:g}kHz'
            if ch:
                lab += ' 单声道' if ch == 1 else (' 立体声' if ch == 2 else f' {ch}ch')
            auds.append(lab.strip())
        if auds:
            out['audio'] = auds
    except Exception as e:
        out['probe_error'] = f'{type(e).__name__}'
    return out


def disc_label(reldir, album_name):
    """碟标签：相对专辑目录的路径，用 · 连接"""
    if not reldir or reldir in ('.', album_name):
        return album_name
    r = os.path.relpath(reldir, album_name)
    parts = [p for p in r.split(os.sep) if p and p != '.']
    return ' · '.join(parts) if parts else album_name


SACD_LOG_RE = re.compile(r'Album (Title|Artist|Performer):\s*(.+)$')


def read_sacd_log(path):
    out = {}
    if not os.path.exists(path):
        return out
    try:
        raw = open(path, 'rb').read()
        txt = decode_text(raw, '')
    except Exception:
        return out
    for ln in txt.splitlines():
        m = SACD_LOG_RE.search(ln)
        if m:
            k = m.group(1).lower()
            if k not in out:
                out[k] = m.group(2).strip()
    return out


def mmss_to_sec(t):
    """07:28:00 [mins:secs:frames] -> 448.0"""
    try:
        parts = t.strip().split()
        mm, ss, ff = parts[0].split(':')
        return round(int(mm) * 60 + int(ss) + int(ff) / 75.0, 1)
    except Exception:
        return None


def parse_disc_info(path):
    """解析 sacd_extract 的碟信息（Disc_summary.txt / *_DISC.txt）：
    带 Track Count 与逐轨 Title/Duration，是镜像里最可信的曲目来源。
    有的版本不给 Duration，那就只取标题。"""
    try:
        raw = open(path, 'rb').read(600000)
    except Exception:
        return None
    txt = decode_text(raw, '')
    if 'Track Count' not in txt or 'Title[' not in txt:
        return None
    out = {'title': '', 'artist': '', 'catalog': '', 'tracks': []}
    m = re.search(r'^\s*Title:\s*(.+)$', txt, re.M)
    if m:
        out['title'] = m.group(1).strip()
    m = re.search(r'^\s*Artist:\s*(.+)$', txt, re.M)
    if m:
        out['artist'] = m.group(1).strip()
    m = re.search(r'Catalog Number:\s*([0-9A-Za-z\- ]+)', txt)
    if m:
        out['catalog'] = m.group(1).strip()
    # 只看第一个 Area（一般是 2 声道层）
    area = txt.split('Area Information [0]:')[-1] if 'Area Information [0]:' in txt else txt
    area = area.split('Area Information [1]:')[0]
    hits = list(re.finditer(r'Title\[([0-9A-Za-z]+)\]:\s*(.+)', area))
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(area)
        block = area[m.end():end]
        dm = re.search(r'Duration:\s*([\d:\.]+)', block)
        out['tracks'].append({
            'no': i + 1,
            'title': m.group(2).strip(),
            'duration': mmss_to_sec(dm.group(1)) if dm else None,
        })
    return out if out['tracks'] else None


ISO_PREFIX_RE = re.compile(r'^(?:ludwig van beethoven|wolfgang amadeus mozart|johannes brahms|'
                           r'herbert von karajan|george-emmanuel lazaridis|giuseppe verdi|'
                           r'richard wagner|peter tschaikowsky|peter ilyich tchaikovsky|'
                           r'anton bruckner|franz liszt)\s*[-–]?\s*', re.I)
ISO_PAIRS_RE = re.compile(r'nos?\.?\s*(\d{1,2})\s*(?:&|and|,|、|\+)\s*(\d{1,2})', re.I)
ISO_RANGE_RE = re.compile(r'nos?\.?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})', re.I)
ISO_SINGLE_RE = re.compile(r'(?:nos?\.?|nr\.?)\s*(\d{1,2})\b', re.I)


PROGRAM_LINE_RE = re.compile(r'^\s*(\d{1,2})\s*[.．、)）]\s*(.+?)\s*$')


def parse_program_txt(path):
    """读「节目单.txt」这类手写曲目单：每行以 1．/ 2. 开头"""
    try:
        txt = decode_text(open(path, 'rb').read(), '')
    except Exception:
        return []
    tracks = []
    for ln in txt.splitlines():
        m = PROGRAM_LINE_RE.match(ln.strip())
        if m:
            title = m.group(2).strip()
            if title and len(title) <= 80:
                tracks.append({'no': len(tracks) + 1, 'title': title, 'duration': None})
    return tracks if len(tracks) >= 5 else []


def find_program_txt(dirpath):
    """在目录里找节目单：优先名字带「节目单/曲目/tracklist」的 txt"""
    cands = []
    for dp, dns, fns in os.walk(dirpath):
        if os.path.relpath(dp, dirpath).count(os.sep) > 1:
            dns[:] = []
            continue
        for fn in fns:
            if fn.lower().endswith('.txt'):
                cands.append(os.path.join(dp, fn))
    SKIP = re.compile(r'歌词|libretto|lyric|译本|对照|对白|字幕|说明|readme', re.I)
    cands = [p for p in cands if not SKIP.search(os.path.basename(p))]
    cands.sort(key=lambda p: (0 if re.search(r'节目单|曲目|track|program', os.path.basename(p), re.I)
                              else 1, len(p)))
    for p in cands:
        t = parse_program_txt(p)
        if t:
            return t
    return []


def infer_titles_from_name(text):
    """从「Symphonies Nos.1&2」「Symphonies 6 & 9」「Symphony No.9」这类名字里
    推出可匹配的曲名；实在没有编号就原样返回。"""
    t = (text or '').strip()
    t = re.sub(r'\.(iso|ISO)$', '', t)
    t = t.replace('_', ' ')
    t = re.sub(r'\[[^\]]*\]', ' ', t)          # 去掉 [Naxos 2011] [SACD] 这类标注
    t = re.sub(r'\s{2,}', ' ', t).strip(' -–')
    for _ in range(3):                          # 叠着的「演出者 - 作曲家」前缀
        t2 = ISO_PREFIX_RE.sub('', t)
        if t2 == t:
            break
        t = t2
    t = re.sub(r'\s{2,}', ' ', t).strip(' -–')

    # 一张碟里有两三部作品时，按分号拆开，各推一条
    if ';' in t or '；' in t:
        parts = [p.strip(' -–') for p in re.split(r'[;；]', t)]
        parts = [p for p in parts if len(p) >= 8]
        if len(parts) >= 2:
            out = []
            for p in parts:
                out.extend(infer_titles_from_name(p))
            return out or [t]

    m = ISO_PAIRS_RE.search(t)
    if m:
        base = t[:m.start()].strip(' -–')
        return [f'{base} No.{a}' for a in (m.group(1), m.group(2))]
    m = ISO_RANGE_RE.search(t)
    if m:
        base = t[:m.start()].strip(' -–')
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= b <= 20 and b - a <= 9:
            return [f'{base} No.{n}' for n in range(a, b + 1)]
    m = ISO_SINGLE_RE.search(t)
    if m:
        base = t[:m.start()].strip(' -–')
        return [f'{base} No.{m.group(1)}']
    # 最后再试「Symphonies 6 & 9」这种连 Nos 都省了的写法
    nums = [int(x) for x in re.findall(r'(?<![\d\u4e00-\u9fff])(\d{1,2})(?![\d])', t)]
    nums = [n for n in nums if 1 <= n <= 20]
    if 1 <= len(nums) <= 4:
        first = re.search(r'(?<![\d\u4e00-\u9fff])\d{1,2}(?![\d])', t)
        base = t[:first.start()].strip(' -–') or t
        return [f'{base} No.{n}' for n in nums]
    return [t] if t else []


def derive_album(name, root, b, store_path=None, parent=None, allow_program=True):
    """把原始文件列表整理为 碟/轨 结构"""
    store = store_path or name
    audio = sorted(b['audio'], key=lambda x: natkey(x['path']))
    for a in audio:
        a['tags'] = read_tags(os.path.join(root, a['path']))
    # 索引 CUE：按所在目录归类
    cue_by_dir = {}
    for c in sorted(b['cue'], key=lambda x: natkey(x['name'])):
        pc = parse_cue(os.path.join(root, c['path']), hint=name)
        if not pc:
            continue
        pc['cue_path'] = c['path']
        pc['cue_dir'] = c['dir']
        nfiles = len([x for x in pc['blocks'] if x['file']])
        pc['mode'] = 'image' if nfiles <= 1 else 'tracks'
        cue_by_dir.setdefault(c['dir'], []).append(pc)

    discs = []
    consumed = set()
    # 1) 单镜像碟：同一个镜像可能配了好几个 CUE（原盘 cue + 自制 cue），取轨数最多的那个
    best_sheet = {}   # image_path -> (img, pc, dir)
    for d, sheets in sorted(cue_by_dir.items(), key=lambda kv: natkey(kv[0])):
        for pc in sheets:
            if pc['mode'] != 'image':
                continue
            img = None
            if pc['blocks'] and pc['blocks'][0]['file']:
                cand = os.path.normpath(os.path.join(d, pc['blocks'][0]['file']))
                for a in audio:
                    if os.path.normpath(a['path']).lower() == cand.lower():
                        img = a
                        break
            if img is None:
                same = [a for a in audio if a['dir'] == d]
                if len(same) == 1:
                    img = same[0]
            if img is None:
                continue
            ntr = len(pc['blocks'][0]['tracks'])
            prev = best_sheet.get(img['path'])
            if prev is None or ntr > len(prev[1]['blocks'][0]['tracks']):
                best_sheet[img['path']] = (img, pc, d)
    def build_image_disc(img, pc, d):
        consumed.add(img['path'])
        tracks = []
        raw_trs = pc['blocks'][0]['tracks']
        starts = [cue_seconds(t['index']) if t['index'] else None for t in raw_trs]
        total = img['tags'].get('duration')
        for i, t in enumerate(raw_trs):
            dur = None
            st = starts[i]
            if st is not None:
                nxt = None
                for j in range(i + 1, len(starts)):
                    if starts[j] is not None and starts[j] > st:
                        nxt = starts[j]
                        break
                if nxt is None and total:
                    nxt = total
                if nxt:
                    dur = round(nxt - st, 1)
            tracks.append({'no': t['no'], 'title': t['title'], 'performer': t['performer'],
                           'index': t['index'], 'duration': dur, 'spec': img['tags'].get('spec', ''),
                           'tags': {}, 'image': True})
        return {'dir': d, 'label': disc_label(d, store), 'image': True,
                'image_path': img['path'], 'image_size': img['size'],
                'image_duration': img['tags'].get('duration'), 'cue': pc['cue_path'],
                'cue_comment': pc['comment'], 'cue_title': pc['title'],
                'tracks': tracks}

    for img_path, (img, pc, d) in sorted(best_sheet.items(), key=lambda kv: natkey(kv[1][2] + kv[0])):
        discs.append(build_image_disc(img, pc, d))
    # 2) 其余音频按目录成碟
    by_dir = {}
    for a in audio:
        if a['path'] in consumed:
            continue
        by_dir.setdefault(a['dir'], []).append(a)
    for d in sorted(by_dir, key=lambda x: natkey(x)):
        files = by_dir[d]
        # 自制 CUE 里的曲名/顺序，按文件名匹配
        title_map = {}
        cue_rank = {}
        r = 0
        for pc in cue_by_dir.get(d, []):
            if pc['mode'] != 'tracks':
                continue
            for blk in pc['blocks']:
                fn = os.path.normpath(os.path.join(d, blk['file'])).lower()
                for tr in blk['tracks']:
                    title_map[fn] = tr['title'] or title_map.get(fn, '')
                    cue_rank.setdefault(fn, r)
                    r += 1
        # 标签里的音轨号只在「正好是 1..n 的一个排列」时才可信
        tns = [a['tags'].get('tracknumber') for a in files]
        tns_ok = all(isinstance(t, int) for t in tns) and sorted(tns) == list(range(1, len(files) + 1))

        def sort_key(a):
            tg = a['tags'] or {}
            fn = os.path.normpath(a['path']).lower()
            return (tg.get('discnumber') or 0,
                    cue_rank.get(fn, 10 ** 6 + (tg.get('tracknumber') if tns_ok else 0)),
                    natkey(a['name']))

        files.sort(key=sort_key)
        tracks = []
        for i, a in enumerate(files, 1):
            tg = a['tags'] or {}
            fn = os.path.normpath(a['path']).lower()
            title = tg.get('title') or title_map.get(fn) or os.path.splitext(a['name'])[0]
            tracks.append({'no': (tg.get('tracknumber') if tns_ok else None) or i, 'title': title,
                           'performer': tg.get('performer') or tg.get('artist') or '',
                           'composer': tg.get('composer', ''), 'duration': tg.get('duration'),
                           'spec': tg.get('spec', ''), 'path': a['path'], 'size': a['size'],
                           'tags': {k: v for k, v in tg.items() if k not in ('spec',)}, 'image': False})
        discs.append({'dir': d, 'label': disc_label(d, store), 'image': False,
                      'tracks': tracks})
    # 3) 只有 ISO 镜像的目录：尽量把镜像里的曲目挖出来
    #    优先用 sacd_extract 的碟信息（Track Count / Title[n] / Duration），
    #    没有就按镜像文件名与所在文件夹名推断能确认的作品。
    discinfo_cache = {}

    def find_discinfo(dirpath, album_dir):
        """找镜像所在目录的碟信息文件；只看这一级和专辑根目录，绝不跨专辑"""
        cands = []
        for base in (dirpath, album_dir):
            if not base or not os.path.isdir(base):
                continue
            try:
                for fn in os.listdir(base):
                    if os.path.splitext(fn)[1].lower() in ('.txt', '.log'):
                        cands.append(os.path.join(base, fn))
            except OSError:
                continue
        seen = set()
        for p in sorted(cands, key=lambda x: ('summary' not in x.lower(), len(x))):
            if p in seen:
                continue
            seen.add(p)
            if p in discinfo_cache:
                info = discinfo_cache[p]
            else:
                info = parse_disc_info(p)
                discinfo_cache[p] = info
            if info:
                return info, p
        return None, None

    album_dir = os.path.join(root, name)
    iso_by_dir = {}
    for x in b['iso']:
        iso_by_dir.setdefault(x['dir'], []).append(x)
    for d in sorted(iso_by_dir, key=lambda x: natkey(x)):
        items = iso_by_dir[d]
        meta = read_sacd_log(os.path.join(root, os.path.join(d, 'sacd_log.txt')))
        info, info_path = find_discinfo(os.path.join(root, d), album_dir)
        tracks = []
        if info:
            for t in info['tracks']:
                tracks.append({'no': t['no'], 'title': t['title'], 'performer': meta.get('artist', ''),
                               'duration': t['duration'], 'spec': 'SACD 镜像内曲目',
                               'tags': {'src': 'meta'}, 'image': False, 'from_meta': True})
            disc_extra = {'cue_title': info.get('title', ''), 'cue_comment': os.path.basename(info_path or '')}
        else:
            # 没有碟信息：按镜像名/文件夹名推断，能确认几首就列几首
            guess_labels = []
            for x in items:
                for g in infer_titles_from_name(x['name']):
                    guess_labels.append((g, os.path.basename(x['name'])))
            if not guess_labels:
                for g in infer_titles_from_name(disc_label(d, name)):
                    guess_labels.append((g, disc_label(d, name)))
            for i, (g, src) in enumerate(guess_labels, 1):
                tracks.append({'no': i, 'title': g, 'performer': meta.get('artist', ''),
                               'duration': None, 'spec': 'SACD 镜像',
                               'tags': {'src': 'name', 'from': src}, 'image': False,
                               'inferred': True})
            disc_extra = {'cue_title': '', 'cue_comment': ''}
        discs.append({'dir': d, 'label': disc_label(d, name), 'image': False, 'iso_disc': True,
                      'iso_files': [x['name'] for x in items],
                      'tracks': tracks, **disc_extra})
    # 只有影像/蓝光、没有任何音轨的专辑
    if not discs and b['video']:
        prog = find_program_txt(os.path.join(root, store)) if allow_program else []
        if prog:
            tracks = [{'no': t['no'], 'title': t['title'], 'performer': '', 'duration': None,
                       'spec': '节目单', 'tags': {'src': 'program'}, 'image': False,
                       'inferred': True} for t in prog]
            streams = [v for v in b['video']
                       if os.path.splitext(v['name'])[1].lower() in ('.m2ts', '.vob', '.ts')]
            discs.append({'dir': store, 'label': '整盘影像（节目单）', 'image': False,
                          'iso_disc': True, 'iso_files': [v['name'] for v in streams][:12],
                          'tracks': tracks, 'cue_title': '', 'cue_comment': 'PROGRAM'})
            guess = None
        else:
            guess = infer_titles_from_name(name)
        if guess is None:
            guess = []
        if guess:
            tracks = [{'no': i, 'title': g, 'performer': '', 'duration': None,
                       'spec': '蓝光/影像内曲目', 'tags': {'src': 'name', 'from': name},
                       'image': False, 'inferred': True}
                      for i, g in enumerate(guess, 1)]
            streams = [v for v in b['video']
                       if os.path.splitext(v['name'])[1].lower() in ('.m2ts', '.vob', '.ts')]
            discs.append({'dir': store, 'label': '蓝光/影像（整段）', 'image': False,
                          'iso_disc': True, 'iso_files': [v['name'] for v in streams][:12],
                          'tracks': tracks, 'cue_title': '', 'cue_comment': 'BD'})

    # 未入碟的音频（理论上不该有）
    used = set()
    for dd in discs:
        for t in dd['tracks']:
            if t.get('path'):
                used.add(t['path'])
    orphans = [a for a in audio if a['path'] not in used and a['path'] not in consumed]
    if orphans:
        discs.append({'dir': name, 'label': '(未归类)', 'image': False,
                      'tracks': [{'no': i, 'title': (a['tags'] or {}).get('title') or a['name'],
                                  'duration': (a['tags'] or {}).get('duration'),
                                  'spec': (a['tags'] or {}).get('spec', ''), 'path': a['path'],
                                  'size': a['size'], 'tags': a['tags'] or {}, 'image': False}
                                 for i, a in enumerate(orphans, 1)]})

    all_tracks = [t for d in discs for t in d['tracks']]
    # 影像/蓝光流：读时长与音轨规格
    for v in b['video']:
        if os.path.splitext(v['name'])[1].lower() in ('.m2ts', '.vob', '.ts'):
            v['probe'] = probe_media(os.path.join(root, v['path']))
    duration = 0.0
    for d in discs:
        ddur = sum((t.get('duration') or 0) for t in d['tracks'])
        if d.get('image') and not ddur:
            ddur = d.get('image_duration') or 0
        duration += ddur
        d['duration'] = round(ddur, 1)
    specs = {}
    for t in all_tracks:
        sp = t.get('spec') or ''
        if sp:
            specs[sp] = specs.get(sp, 0) + 1
    size = sum(x['size'] for k in ('audio', 'iso', 'video') for x in b[k])
    return {
        'name': name, 'path': store, 'kind': 'album', 'group': parent,
        'discs': discs,
        'tracks': all_tracks,
        'stats': {'n_audio': len(b['audio']), 'n_tracks': len(all_tracks), 'n_discs': len(discs),
                  'duration': round(duration, 1), 'size': size, 'specs': specs,
                  'n_iso': len(b['iso']), 'n_video': len(b['video']), 'n_art': len(b['art']),
                  'n_doc': len(b['doc']), 'n_junk': len(b['junk'])},
        'iso': b['iso'], 'video': b['video'], 'art': b['art'], 'doc': b['doc'], 'junk': b['junk'],
        'cue_sheets': [pc for v in cue_by_dir.values() for pc in v],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.environ.get('MUSIC_ROOT', ''),
                    help='音乐库根目录；也可用环境变量 MUSIC_ROOT')
    args = ap.parse_args()
    root = args.root
    if not root:
        sys.exit('请用 --root 或环境变量 MUSIC_ROOT 指定音乐库根目录')
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
    os.makedirs(out_dir, exist_ok=True)

    entries = sorted([e for e in os.scandir(root) if not e.name.startswith('_目录')],
                     key=lambda e: natkey(e.name))
    albums, loose = [], []
    for de in entries:
        if de.is_dir(follow_symlinks=False):
            b = collect(de.path, root)
            if not any(b[k] for k in b):
                albums.append({'name': de.name, 'path': de.name, 'kind': 'empty',
                               'discs': [], 'tracks': [],
                               'stats': {'n_audio': 0, 'n_tracks': 0, 'n_discs': 0, 'duration': 0,
                                         'size': 0, 'specs': {}, 'n_iso': 0, 'n_video': 0,
                                         'n_art': 0, 'n_doc': 0, 'n_junk': 0},
                               'iso': [], 'video': [], 'art': [], 'doc': [], 'junk': [], 'cue_sheets': []})
                continue
            # 影像合集（例如 [_DVD]）：没有音频、没有镜像，但片子按子目录分装
            subs = []
            try:
                subs = sorted(d for d in os.listdir(de.path)
                              if os.path.isdir(os.path.join(de.path, d)) and not d.startswith('.'))
            except OSError:
                pass
            is_container = (not b['audio'] and not b['iso'] and b['video'] and len(subs) >= 3)
            if is_container:
                for sd in subs:
                    sub_path = os.path.join(de.path, sd)
                    b2 = collect(sub_path, root)
                    if not any(b2[k] for k in b2):
                        continue
                    alb = derive_album(sd, root, b2, store_path=os.path.join(de.name, sd),
                                       parent=de.name)
                    albums.append(alb)
                    print('  ok', de.name, '/', sd, flush=True)
                # 合集根目录上散落的东西（比如一个单独的 .vob）单独成一条
                top_video = [v for v in b['video'] if os.path.dirname(v['path']) == de.name]
                if top_video:
                    b3 = {k: [] for k in b}
                    b3['video'] = top_video
                    if len(top_video) == 1:
                        solo = os.path.splitext(top_video[0]['name'])[0]
                    else:
                        solo = de.name + ' · 其余影像'
                    alb = derive_album(solo, root, b3, store_path=de.name,
                                       parent=de.name, allow_program=False)
                    albums.append(alb)
                continue
            albums.append(derive_album(de.name, root, b, store_path=de.name))
            print('  ok', de.name, flush=True)
        else:
            ext = os.path.splitext(de.name)[1].lower()
            st = de.stat()
            ent = {'name': de.name, 'path': de.name, 'size': st.st_size, 'mtime': int(st.st_mtime)}
            if ext in AUDIO_EXT:
                ent['tags'] = read_tags(de.path)
                ent['type'] = 'audio'
            elif ext in ISO_EXT:
                ent['type'] = 'iso'
            elif ext in VIDEO_EXT:
                ent['type'] = 'video'
            else:
                ent['type'] = 'doc'
            loose.append(ent)
    data = {'root': root, 'generated_ts': int(time.time()), 'albums': albums, 'loose': loose}
    p = os.path.join(out_dir, 'inventory.json')
    json.dump(data, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n_tracks = sum(a['stats']['n_tracks'] for a in albums)
    print('WROTE', p)
    print('albums:', len(albums), 'tracks:', n_tracks, 'loose:', len(loose))


if __name__ == '__main__':
    main()

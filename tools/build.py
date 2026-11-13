# -*- coding: utf-8 -*-
r"""
把 inventory.json + 知识库 JSON 渲染成一本单文件 HTML 目录（GitHub Pages 版）。

用法：
    python build.py                     # 常规重建（自动升版本、归档旧版、记日志）
    python build.py --note "补了X张"     # 带一句更新说明
    python build.py --dev               # 开发用：写 _dev.html，不升版本/不归档/不写日志
    python build.py --no-covers         # 不导出封面（不想把唱片封面传到公开仓库时用）

目录结构（本文件所在位置 = 仓库根下的 tools\）：
    docs\index.html                发布入口（GitHub Pages 的文档根）
    docs\assets\covers\*.jpg       封面（自动从音乐库取、压到 1000px）
    docs\assets\covers\t\*.jpg     列表用缩略图（420px）
    docs\.nojekyll                 告诉 Pages 别走 Jekyll
    data\inventory.json            扫描结果
    data\knowledge\*.json          讲解内容
    data\state.json                版本号与指纹
    archive\*.html                 本机留档的旧版
    更新日志.md                     人类可读的变更记录
"""
import argparse
import glob
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse

for _st in (sys.stdout, sys.stderr):
    try:
        _st.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = os.environ.get('MUSIC_ROOT', '').strip()   # 音乐库位置；只有导出封面时需要
# 例：set MUSIC_ROOT=D:\Music   （不带封面出站点不需要它）
CDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根 = tools 的上一级
SITE = os.path.join(CDIR, 'docs')           # GitHub Pages 发布目录
DATA = os.path.join(CDIR, 'data')
KN = os.path.join(DATA, 'knowledge')
COVERS = os.path.join(SITE, 'assets', 'covers')
COVERS_T = os.path.join(COVERS, 't')
OUT_HTML = os.path.join(SITE, 'index.html')
DEV_HTML = os.path.join(SITE, '_dev.html')
ARCHIVE = os.path.join(CDIR, 'archive')
STATE = os.path.join(DATA, 'state.json')
# 公开版：页面里不出现任何本机路径/文件名/占用空间。--local 可切回带文件信息的版本
PUBLIC = True
LOG = os.path.join(CDIR, '更新日志.md')


# ---------------------------------------------------------------- 标志（矢量，内联）
# 直角方形：黄底 + 黑描边的方框与倒三角，比例取自原图（500×500 画布）
BOX, TRI = '<rect x="88.5" y="148.5" width="197" height="277"/>', '167.4,73.5 422.1,73.5 294.4,407.5'
IBOX, ITRI = '<rect x="97" y="157" width="180" height="260"/>', '175,80 415,80 295,400'
LOGO_MODE = os.environ.get('LOGO_MODE', 'both')       # both / bar / mast / none


def svg_mark(px=0, stroke=19, box=BOX, tri=TRI, fg='#000000', bg='#FFC90E', cls=''):
    size = f' width="{px}" height="{px}"' if px else ''
    c = f' class="{cls}"' if cls else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg"{c}{size} viewBox="0 0 500 500" '
            f'aria-hidden="true" focusable="false">'
            f'<rect width="500" height="500" fill="{bg}"/>'
            f'<g fill="none" stroke="{fg}" stroke-width="{stroke}" stroke-miterlimit="4">'
            f'{box}<polygon points="{tri}"/></g></svg>')


def favicon(online):
    """标签页图标：在线黄底黑图，离线黑底黄图——看一眼就知道开的是哪一版"""
    fg, bg = ('#000000', '#FFC90E') if online else ('#FFC90E', '#141414')
    return 'data:image/svg+xml,' + urllib.parse.quote(
        svg_mark(0, 34, IBOX, ITRI, fg, bg), safe='')

# ---------------------------------------------------------------- 小工具
def esc(t):
    return html.escape(str(t if t is not None else ''), quote=True)


def fmt_dur(sec):
    if not sec:
        return '—'
    sec = int(round(sec))
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def fmt_dur_cn(sec):
    if not sec:
        return '—'
    sec = int(round(sec))
    h, m = sec // 3600, (sec % 3600) // 60
    return f'{h} 小时 {m} 分' if h else f'{m} 分钟'


def fmt_size(b):
    if not b:
        return '—'
    for u in ('B', 'KB', 'MB', 'GB'):
        if b < 1024:
            return f'{b:.0f} {u}'
        b /= 1024
    return f'{b:.1f} TB'


def aid(name):
    return 'a-' + hashlib.md5(name.encode('utf-8')).hexdigest()[:8]


def url_path(rel):
    return '/'.join(urllib.parse.quote(p) for p in rel.replace('\\', '/').split('/'))


def natkey(t):
    return [int(x) if x.isdigit() else str(x).lower() for x in re.split(r'(\d+)', t or '')]


# ---------------------------------------------------------------- 分类
CATS = [
    ('beethoven', '贝多芬', ['beethoven', '贝多芬']),
    ('mozart', '莫扎特 · 舒伯特', ['mozart', '莫扎特', 'schubert', '舒伯特']),
    ('shostakovich', '肖斯塔科维奇', ['shostakovich', '肖斯塔科维奇', 'scriabin', '斯克里亚宾']),
    ('strauss', '施特劳斯家族', ['strauss', '施特劳斯']),
    ('russian-classical', '柴可夫斯基 · 拉赫玛尼诺夫 · 德沃夏克',
     ['tchaikovsky', '柴可夫斯基', 'rachmanin', '拉赫玛尼诺夫', 'dvorak', '德沃夏克', 'smetana', '斯美塔那']),
    ('others', '其他古典', ['holst', '霍尔斯特', 'vivaldi', '维瓦尔第', 'khachaturian', '哈恰图良',
                            'mendelssohn', '门德尔松', 'rossini', '罗西尼', 'wagner', '瓦格纳',
                            'suppe', '苏佩', 'bizet', 'brahms', 'chopin', 'liszt']),
    ('chinese', '中国作品', ['梁祝', '俞丽拿', '中国唱片', '中唱']),
    ('russian-song', '俄苏歌曲', ['_俄语', 'пахмутова', 'ансамбл', 'кино', 'калинка', 'день победы']),
    ('pop', '流行 · 试音', ['_流行', 'eagles', '蔡琴', '惠威', '张学友']),
    ('av', '影像 · 镜像', ['_dvd', '_解释']),
]


def classify(al, kn):
    hay = ' '.join(filter(None, [al['name'], (kn or {}).get('composer', ''),
                                 (kn or {}).get('performer', '')])).lower()
    for key, label, kws in CATS:
        for kw in kws:
            if kw in hay:
                return key, label
    return 'others', '其他古典'


# ---------------------------------------------------------------- 知识库
def load_knowledge():
    load_aliases()
    albums, works, loose = {}, {}, {}
    conflicts = []
    files = sorted(glob.glob(os.path.join(KN, '*.json')))
    # _manual.json 最后加载，用于人工覆盖
    files.sort(key=lambda p: (os.path.basename(p) == '_manual.json', p))
    for p in files:
        base = os.path.basename(p)
        if base.startswith('_') and base != '_manual.json':
            continue      # _aliases.json / _SCHEMA.md 之类不是知识条目
        try:
            d = json.load(open(p, encoding='utf-8-sig'))
        except Exception as e:
            print(f'  !! 跳过 {os.path.basename(p)}: {e}')
            continue
        for a in d.get('albums', []) or []:
            n = (a.get('name') or '').strip()
            if not n:
                continue
            is_manual = os.path.basename(p) == '_manual.json'
            if n in albums:
                if is_manual:
                    albums[n].update({k: v for k, v in a.items() if v not in (None, '', [])})
                else:
                    conflicts.append(('album', n, os.path.basename(p)))
                continue
            albums[n] = a
        for w in d.get('works', []) or []:
            wid = (w.get('id') or '').strip() or (w.get('title') or '').strip()
            if not wid:
                continue
            is_manual = os.path.basename(p) == '_manual.json'
            if wid in works:
                if is_manual:
                    # match 是「追加」而不是覆盖：补丁只补漏网写法，不废掉原来的规则
                    extra = list(w.get('match') or [])
                    drops = list(w.get('match_drop') or [])
                    works[wid].update({k: v for k, v in w.items()
                                       if k not in ('match', 'match_drop') and v not in (None, '', [])})
                    if extra:
                        works[wid]['match'] = list(works[wid].get('match') or []) + [
                            m for m in extra if m not in (works[wid].get('match') or [])]
                    if drops:
                        works[wid]['match'] = [m for m in (works[wid].get('match') or [])
                                               if m not in drops]
                    works[wid]['_id'] = wid
                else:
                    conflicts.append(('work', wid, os.path.basename(p)))
                continue
            w['_id'] = wid
            works[wid] = w
        for x in d.get('loose', []) or []:
            n = (x.get('name') or '').strip()
            if n:
                loose[n] = x
    # 预编译正则，长的优先（更具体的先匹配）
    ws = sorted(works.values(), key=lambda w: -max([len(m) for m in (w.get('match') or [''])] or [0]))
    for w in ws:
        pats = []
        for m in (w.get('match') or []):
            try:
                pats.append(re.compile(m, re.I))
            except re.error:
                pass
        w['_pats'] = pats
        w['_mv'] = w.get('movements') or []
        w['_no'] = work_number(w)
        w['_aliases'] = auto_aliases(w)
        w['_genres'] = genres_of(' '.join(filter(None, [w.get('title'), w.get('id')] +
                                                    list(w.get('aka') or []))))
        for i, mv in enumerate(w['_mv'], 1):
            mv['n'] = mv.get('n') or i
    return albums, ws, works, loose, conflicts


ROMAN = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8,
         'ix': 9, 'x': 10, 'xi': 11, 'xii': 12, 'xiii': 13, 'xiv': 14, 'xv': 15,
         'xvi': 16, 'xvii': 17, 'xviii': 18, 'xix': 19, 'xx': 20}
NUM_HEAD = re.compile(r'^\s*(?:第\s*)?(\d{1,2}|[ivxIVX]{1,6})\s*[\.、．:：\-–—)）]?\s*(?=[A-Za-zÀ-ÿА-я\u4e00-\u9fff])')
# 标题里的「… 3. Adagio」「… - IV」这类乐章号（取最后一处）
NUM_TAIL = re.compile(r'(?:[-–—:：]|\s)\s*(\d{1,2})\s*[\.、．)）]\s*(?=[A-Za-zÀ-ÿА-я\u4e00-\u9fff])')
# 「Nr. 2.」「Op.19.」里的数字是作品号，不是乐章号
NUM_TAIL_SKIP = re.compile(r'(?:nr|no|op|kv|k|bwv|d|hob|woo)\.?\s*$', re.I)
ROMAN_TAIL = re.compile(r'(?:[-–—:：]|\s)\s*(I{1,3}|IV|VI{0,3}|IX|XI{0,3}|XIV|XV)\s*$')

# 体裁词：挡住「作品号撞车」的误配（Op.15 的奏鸣曲被当成 Op.15 的协奏曲）
GENRES = {
    'symphony': ['symphon', '交响', 'sinfonia'],
    'concerto': ['concerto', 'konzert', '协奏曲'],
    'sonata': ['sonata', 'sonate', '奏鸣曲'],
    'suite': ['suite', '组曲'],
    'overture': ['overture', 'ouverture', '序曲'],
    'mass': ['mass', 'messe', '弥撒'],
    'quartet': ['quartet', 'quartett', '四重奏'],
    'song': ['lied', 'songs', '歌曲', '艺术歌曲'],
    'ballet': ['ballet', '芭蕾'],
    'poem': ['dichtung', 'poème', 'poem', '交响诗'],
    'waltz': ['walzer', 'waltz', '圆舞曲'],
    'serenade': ['serenade', '小夜曲'],
    'divertimento': ['divertimento', '嬉游曲'],
    'variation': ['variation', '变奏'],
    'fantasy': ['fantas', '幻想'],
    'opera': ['opera', '乐剧', '歌剧'],
    'cantata': ['cantata', '清唱剧'],
    'oratorio': ['oratorio', '受难曲', 'passion'],
}


def genres_of(text):
    t = (text or '').lower()
    return {g for g, kws in GENRES.items() if any(k in t for k in kws)}


def head_number(title):
    """从标题里取乐章号：先找标题末尾的编号，再找开头的编号"""
    t = title or ''
    tail = None
    for m in NUM_TAIL.finditer(t):
        if NUM_TAIL_SKIP.search(t[:m.start() + 1]):
            continue
        n = int(m.group(1))
        if 1 <= n <= 60:
            tail = n
    if tail:
        return tail
    m = ROMAN_TAIL.search(t)
    if m:
        n = ROMAN.get(m.group(1).lower())
        if n:
            return n
    m = NUM_HEAD.match(t)
    if m:
        tok = m.group(1)
        if tok.isdigit():
            n = int(tok)
            return n if 1 <= n <= 60 else None
        return ROMAN.get(tok.lower())
    return None


def name_match_score(mv_name, title):
    """乐章名与音轨标题的字面重合度（0–1），用于兜底匹配"""
    if not mv_name:
        return 0.0
    t = re.sub(r'[^a-zа-я\u4e00-\u9fff]', '', (title or '').lower())
    n = re.sub(r'[^a-zа-я\u4e00-\u9fff]', '', mv_name.lower())
    if len(n) < 4:
        return 0.0
    for L in (14, 10, 7):
        if len(n) >= L and n[:L] in t:
            return L / 14.0
    return 0.0


CJK_OR_EN = re.compile(r'[a-z]{4,}|[\u4e00-\u9fff]{2,}')


CN_NUM = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
          '十': 10, '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15}
WORK_NO_CJK = re.compile(r'第\s*([一二三四五六七八九十]{1,3}|\d{1,2})\s*(?:交响曲|交响乐|奏鸣曲|协奏曲|组曲|交响诗|序曲)')
WORK_NO_EN = re.compile(r'\bno\.?\s*(\d{1,2})\b', re.I)
TRACK_NO_GENRE = re.compile(r'(?:sinfon[ií]a|sinfonie|symphon\w*|symphonie)\s*(?:no\.?|nr\.?)?\s*(\d{1,2})\b', re.I)


def work_number(w):
    txt = ' '.join(filter(None, [w.get('title'), w.get('_id')]))
    m = WORK_NO_CJK.search(txt or '')
    if m:
        t = m.group(1)
        return int(t) if t.isdigit() else CN_NUM.get(t)
    m = WORK_NO_EN.search(txt or '')
    if m:
        return int(m.group(1))
    return None


def title_number(t):
    m = TRACK_NO_GENRE.search(t or '')
    if m:
        return int(m.group(1))
    m = re.search(r'\bnr\.?\s*(\d{1,2})\b', t or '', re.I)
    if m:
        return int(m.group(1))
    return None


def composer_key(s):
    return set(CJK_OR_EN.findall((s or '').lower()))


def find_work_scored(works, title, pref=None):
    """返回 (作品, 命中的标题片段长度)；长度越大越可信"""
    gt = genres_of(title)
    cands = []
    for w in works:
        gw = w.get('_genres') or set()
        best = 0
        for p in w['_pats']:
            m = p.search(title or '')
            if m:
                best = max(best, len(m.group(0)))
        if not best:
            continue
        if gw and gt and not (gw & gt):
            continue
        weak = best <= 7 and not (gw & gt)
        if weak and pref and not (composer_key(w.get('composer')) & pref):
            continue
        cands.append((w, best, bool(gw & gt)))
    if not cands:
        return None, 0
    if pref:
        ok = [c for c in cands if composer_key(c[0].get('composer')) & pref]
        if ok:
            cands = ok
        else:
            strong = [c for c in cands if c[1] >= 20 and c[2]]
            if not strong:
                return None, 0
            cands = strong
    cands.sort(key=lambda c: (-c[1], -int(c[2])))
    return cands[0][0], cands[0][1]


def find_work(works, title, pref=None):
    """在标题里找作品。
    - pref：专辑作曲家的词根集合，排除同号不同人的作品串台；
    - 体裁冲突（Op.15 奏鸣曲 vs Op.15 协奏曲）直接否掉；
    - 命中片段太短又无体裁佐证时，只认作曲家对得上的。"""
    gt = genres_of(title)
    cands = []
    for w in works:
        gw = w.get('_genres') or set()
        best = 0
        for p in w['_pats']:
            m = p.search(title or '')
            if m:
                best = max(best, len(m.group(0)))
        if not best:
            continue
        if gw and gt and not (gw & gt):
            continue          # 体裁打架：不是这部作品
        wn, tn = w.get('_no'), title_number(title)
        if wn and tn and wn != tn:
            continue          # 作品号写的是这部、标题里的编号却不是，多半是撞车
        weak = best <= 7 and not (gw & gt)
        if weak and pref and not (composer_key(w.get('composer')) & pref):
            continue          # 太弱的匹配，又不是这位作曲家的，丢掉
        cands.append((w, best, bool(gw & gt)))
    if not cands:
        return None
    if pref:
        ok = [c for c in cands if composer_key(c[0].get('composer')) & pref]
        if ok:
            cands = ok
        else:
            # 作曲家对不上：只接受「命中片段够长 + 体裁吻合」的强证据，否则宁可认不出
            strong = [c for c in cands if c[1] >= 20 and c[2]]
            if not strong:
                return None
            cands = strong
    # 命中的标题片段最长者优先，其次有体裁佐证的
    cands.sort(key=lambda c: (-c[1], -int(c[2])))
    return cands[0][0]


# ---------------------------------------------------------------- 曲目分组
def flatten_hints(tw, discs):
    """把「按碟给的 track_works」摊平成与全专辑音轨顺序对齐的一维数组"""
    if not tw:
        return None
    if not isinstance(tw[0], list):
        return tw
    flat = []
    for i, d in enumerate(discs):
        n = len(d['tracks'])
        sub = list(tw[i])[:n] if i < len(tw) else []
        flat.extend(sub + [''] * (n - len(sub)))
    return flat


INF_GENRE_RE = re.compile(
    r'\b(symphon\w*|sinfon\w*|sonat\w*|sonate|concerto|konzert|suite|quartet|'
    r'divertimento|serenade|mass|messe|ballet|etoile|etude|studie)', re.I)
INF_GENRE_MAP = {
    'symphony': 'symphony', 'symphonies': 'symphony', 'sinfonie': 'symphony',
    'sonata': 'sonata', 'sonate': 'sonata', 'concerto': 'concerto', 'konzert': 'concerto',
    'suite': 'suite', 'quartet': 'quartet', 'divertimento': 'divertimento',
    'serenade': 'serenade', 'mass': 'mass', 'messe': 'mass', 'ballet': 'ballet',
}
WORK_GENRE_MAP = {'symphony': 'symphony', 'concerto': 'concerto', 'sonata': 'sonata',
                  'suite': 'suite', 'ballet': 'suite', 'divertimento': 'divertimento',
                  'serenade': 'serenade', 'mass': 'mass', 'quartet': 'quartet',
                  # work_numbers() 返回中文体裁，这里归一
                  '交响曲': 'symphony', '协奏曲': 'concerto', '钢琴协奏曲': 'concerto',
                  '小提琴协奏曲': 'concerto', '奏鸣曲': 'sonata', '组曲': 'suite',
                  '芭蕾': 'suite', '嬉游曲': 'divertimento', '小夜曲': 'serenade',
                  '弥撒': 'mass', '四重奏': 'quartet'}


def find_work_by_number(works, title, pref=None):
    """给「Symphony No.9」这种自己推断出来的曲名用：体裁 + 编号直接对，不跑正则"""
    m = INF_GENRE_RE.search(title or '')
    if not m:
        return None
    g = INF_GENRE_MAP.get(m.group(1).lower())
    if not g:
        return None
    n = title_number(title)
    if not n:
        return None
    cands = []
    for w in works:
        genre, num, opus, kv = work_numbers(w)
        if not genre or WORK_GENRE_MAP.get(genre) != g:
            continue
        try:
            wn = int(num) if str(num).isdigit() else int(CN_TO_INT.get(str(num)) or 0)
        except Exception:
            wn = 0
        if wn != n:
            continue
        cands.append(w)
    if not cands:
        return None
    if pref:
        ok = [w for w in cands if composer_key(w.get('composer')) & pref]
        if ok:
            return ok[0]
        return None          # 作曲家对不上就不要，宁可认不出
    # 没有作曲家线索而又有多个同号作品（例如三首「第九交响曲」）时不要瞎猜
    return cands[0] if len(cands) == 1 else None


def group_tracks(works, tracks, hints=None, wmap=None, pref=None, anchor=None):
    """把连续属于同一作品的音轨归成一组：[{work, tracks:[...]}]
    hints: 与 tracks 等长的作品 id 数组，用于标题里看不出作品名、只能按顺序判断的专辑。
    pref: 专辑作曲家的词根集合，用来防止同号不同人的作品串台。"""
    groups = []
    cur = None
    for i, t in enumerate(tracks):
        title = t.get('title') or ''
        if t.get('inferred'):
            w = find_work_by_number(works, title, pref)
            score = 99 if w else 0
            if not w:
                w, score = find_work_scored(works, title, pref)
        else:
            w, score = find_work_scored(works, title, pref)
        # 专辑名已经点明是哪一部（如「Götterdämmerung」）时，弱匹配到别的曲子就改判
        if anchor and w is not None and w is not anchor and score < 12:
            w = anchor
        if w is None and hints and i < len(hints) and hints[i] and wmap:
            w = wmap.get(hints[i])
        if w is None:
            if not groups or groups[-1]['work'] is not None:
                groups.append({'work': None, 'tracks': []})
            groups[-1]['tracks'].append(t)
            cur = None
            continue
        if cur is not w:
            groups.append({'work': w, 'tracks': []})
            cur = w
        groups[-1]['tracks'].append(t)
    # 续接：镜像 CUE 常常只有第一轨写作品名（「… KV.525 - 1. Allegro」），后面几轨只剩
    # 「2. Romance. Andante」。若前一组作品的乐章还没配满，就把紧跟其后的无主轨接进去。
    merged = []
    for g in groups:
        if merged and g['work'] is None:
            prev = merged[-1]
            if prev['work'] is not None and prev['work']['_mv']:
                have = len(prev['tracks'])
                need = len(prev['work']['_mv']) - have
                cand = g['tracks']
                if 0 < need and 0 < len(cand) <= need:
                    nums = [head_number(t.get('title')) for t in cand]
                    ok = all(n is not None and have < n <= len(prev['work']['_mv']) for n in nums)
                    if ok:
                        prev['tracks'].extend(cand)
                        continue
        merged.append(g)
    groups = merged
    # 逐组解析乐章号
    for g in groups:
        w = g['work']
        mvs = w['_mv'] if w else []
        seq = 0
        for t in g['tracks']:
            seq += 1
            mv = None
            if mvs:
                n = head_number(t.get('title'))
                if n:
                    mv = next((m for m in mvs if m['n'] == n), None)
                if mv is None:
                    best, best_s = None, 0.0
                    for m in mvs:
                        sc = name_match_score(m.get('name'), t.get('title'))
                        if sc > best_s:
                            best, best_s = m, sc
                    mv = best
                if mv is None and mvs:
                    # 顺序兜底：超出乐章数的轨（拆轨、掌声、闭场广播）归到末乐章
                    mv = mvs[seq - 1] if seq <= len(mvs) else mvs[-1]
            t['_mv'] = mv
    return groups


# ---------------------------------------------------------------- 指纹
def fingerprint(al):
    st = al['stats']
    sig = [st['n_tracks'], st['n_discs'], round(st['duration'], 1),
           [d['label'] for d in al['discs']],
           [t.get('title') for t in al['tracks']][:5],
           [t.get('title') for t in al['tracks']][-3:]]
    return hashlib.md5(json.dumps(sig, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]


def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE, encoding='utf-8'))
        except Exception:
            pass
    return {'version': 0, 'history': [], 'albums': {}}


# ---------------------------------------------------------------- 渲染
CSS = r"""
:root{--fg:#1c1a17;--dim:#6b635b;--line:#e2dcd3;--bg:#fbf9f5;--card:#fff;--acc:#8c2f1e;
--tag:#f0e9df;--code:#f4f1ec;--hi:#fff6d8;}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
/* 字体策略：西文/西里尔交给 Times New Roman（宋体的俄文字形很难看），
   汉字走「思源宋 → 华文宋 → 方正书宋 → 宋体」——前三个都是轮廓字体，小字号没有宋体的点阵锯齿 */
:root{--serif:"Times New Roman",Times,"Nimbus Roman","Noto Serif SC","Source Han Serif SC",
 "Songti SC","华文宋体","STSong","方正书宋_GBK","宋体",SimSun,serif;
 --sans:"Microsoft YaHei","微软雅黑","PingFang SC","Hiragino Sans GB","Segoe UI",Arial,sans-serif;
 --mono:Consolas,"Cascadia Mono","DejaVu Sans Mono","Noto Serif SC","宋体",monospace;}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.78 var(--serif);}
html.sans body{font:16.5px/1.75 var(--sans);}
html.sans .files code,html.sans table.tracks{font-family:var(--sans)}
a{color:var(--acc);text-decoration:none;border-bottom:1px solid rgba(140,47,30,.25)}
a:hover{background:var(--hi);border-bottom-color:var(--acc)}
.wrap{max-width:1080px;margin:0 auto;padding:0 22px 90px}
header.top{position:sticky;top:0;z-index:20;background:rgba(251,249,245,.96);
 backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
header.top .bar{max-width:1080px;margin:0 auto;padding:9px 22px;display:flex;gap:14px;align-items:center}
header.top b{font-size:15px;letter-spacing:.04em;white-space:nowrap}
.brand{display:inline-flex;align-items:center;gap:9px;color:inherit;border:0;text-decoration:none;padding:0}
.brand:hover{background:none;border:0}
.brand svg{flex:none;border-radius:3px}
.brand .tx{border-bottom:1px solid transparent}
.brand:hover .tx{border-bottom-color:var(--acc)}
.mast{display:flex;align-items:center;gap:16px;margin:34px 0 6px}
.mast h1{margin:0}
.mast svg{flex:none;border-radius:4px;box-shadow:0 1px 2px rgba(70,50,20,.18)}
@media(max-width:640px){.brand svg{display:none}.mast svg{width:50px;height:50px}}
[id]{scroll-margin-top:80px}
header.top input{flex:1;min-width:120px;padding:7px 11px;border:1px solid var(--line);border-radius:6px;
 background:#fff;font:inherit;font-size:14px;color:var(--fg)}
header.top .hint{font-size:12.5px;color:var(--dim);white-space:nowrap}
h1{font-size:34px;line-height:1.25;margin:34px 0 6px;letter-spacing:.01em}
.sub{color:var(--dim);font-size:14px;margin-bottom:18px}
h2{font-size:23px;margin:44px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--fg);letter-spacing:.01em}
h3{font-size:18px;margin:26px 0 10px}
h4{font-size:15px;margin:20px 0 8px;color:var(--dim);font-weight:600;letter-spacing:.03em}
p{margin:.55em 0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.card .k{font-size:12.5px;color:var(--dim);letter-spacing:.06em}
.card .v{font-size:20px;font-weight:600;margin-top:2px}
.card .s{font-size:12.5px;color:var(--dim)}
.toc{columns:2;column-gap:34px;margin-top:10px}
@media(max-width:760px){.toc{columns:1}}
.toc .grp{break-inside:avoid;margin:0 0 18px}
.toc .grp>.gh{font-size:13px;letter-spacing:.08em;color:var(--dim);font-weight:600;
 border-bottom:1px solid var(--line);padding-bottom:4px;margin-bottom:6px}
.toc ol{list-style:none;margin:0;padding:0;font-size:14.5px}
.toc li{margin:3px 0;line-height:1.45;padding-left:2.1em;text-indent:-2.1em}
.toc li .n{color:var(--dim);font-size:12.5px;display:inline-block;width:2.1em;text-indent:0}
.toc li .d{display:block;font-size:13px;color:var(--dim);text-indent:0;padding-left:2.1em}
.album{background:var(--card);border:1px solid var(--line);border-radius:10px;
 padding:20px 24px 24px;margin:26px 0}
.album h2.title{font-size:22px;border:0;margin:0 0 4px;padding:0;line-height:1.35}
.album .num{color:var(--acc);font-size:13px;letter-spacing:.12em;font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 4px}
.chip{font-size:13px;background:var(--tag);border-radius:20px;padding:2px 10px;color:#4a423a}
.chip.k{background:#f6efe6;color:#7a6a56}
.oneliner{margin:12px 0 4px;font-size:17.5px;color:#2a2620;border-left:3px solid var(--acc);
 padding:2px 0 2px 12px}
.note{background:#faf7f2;border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
.note h5{margin:0 0 4px;font-size:14px;letter-spacing:.05em;color:var(--acc)}
.note p{margin:.2em 0;font-size:15px;line-height:1.72}
.cmp{font-size:14px;color:#4a423a;margin:14px 0 0;padding:10px 14px;background:#f7f4ee;
 border-radius:8px;border:1px dashed var(--line)}
.cmp b{color:var(--dim);font-weight:600;font-size:13px;letter-spacing:.06em}
table.tracks{width:100%;border-collapse:collapse;margin:8px 0 4px;font-size:15px}
table.tracks td{padding:5px 8px;border-bottom:1px solid #efeae2;vertical-align:top}
table.tracks td.no{width:2.6em;color:var(--dim);font-size:13px;text-align:right;font-variant-numeric:tabular-nums}
table.tracks td.ti{width:auto}
table.tracks td.du{width:4.2em;color:var(--dim);font-size:13px;text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
table.tracks tr.mv td.ti{font-weight:600}
table.tracks tr.inf td.ti{font-weight:400;color:#7d7368;font-style:normal}
table.tracks tr.inf td.no{color:#c0b6a8}
.sortnote{font-size:13.5px;color:#5c534a;background:#f7f4ee;border-left:3px solid #d8cbb6;padding:8px 14px;border-radius:0 6px 6px 0;line-height:1.7;margin:8px 0 12px}
.sortnote b{color:var(--acc)}
.arcnote{background:#fdf8ee;border:1px solid #ecdfc6;border-radius:6px;padding:8px 12px;font-size:13px;color:#6b5a3e;margin:6px 0 10px}
table.tracks tr.about td{font-size:14.3px;color:#3d372f;padding-top:0;padding-bottom:10px;
 border-bottom:1px solid #efeae2;line-height:1.72}
.workbox{border-left:2px solid #ddd4c7;padding-left:14px;margin:18px 0 10px}
.workhead{font-size:15.5px;font-weight:600;margin-bottom:2px}
.workhead .who{font-size:12.5px;color:var(--dim);font-weight:400;margin-left:8px}
.workabout{font-size:14.3px;color:#3d372f;background:#faf8f3;border-radius:6px;padding:8px 12px;margin:6px 0 4px}
details{margin:14px 0 0}
summary{cursor:pointer;font-size:13.5px;color:var(--dim);letter-spacing:.04em;outline:none}
summary:hover{color:var(--acc)}
.files{font-size:13.3px;color:#4a423a;margin-top:8px}
.files code{background:var(--code);border-radius:4px;padding:1px 5px;font-size:12.8px;
 font-family:var(--mono);word-break:break-all}
.ftbtn{font:inherit;font-size:13px;line-height:1.2;padding:5px 10px;border:1px solid var(--line);background:#fff;border-radius:6px;color:var(--dim);cursor:pointer;white-space:nowrap}
.ftbtn:hover{color:var(--acc);border-color:var(--acc)}
.tag{display:inline-block;font-size:12px;background:#f2ece2;color:#6d5b45;border-radius:4px;
 padding:1px 7px;margin-left:6px;vertical-align:2px}
.cover{float:right;width:168px;margin:0 0 12px 18px;border:1px solid var(--line);border-radius:6px;
 box-shadow:0 2px 8px rgba(0,0,0,.06)}
.cover.cph{aspect-ratio:1/1;display:flex;flex-direction:column;justify-content:space-between;
 padding:12px 13px;overflow:hidden;border-color:hsl(var(--h) 30% 78%);
 background:linear-gradient(155deg,hsl(var(--h) 40% 94%),hsl(var(--h) 28% 85%));
 color:hsl(var(--h) 42% 30%);font-size:11.5px;line-height:1.32}
.cover.cph .cph-n{font:600 12px/1 "Times New Roman",serif;letter-spacing:.16em;opacity:.55}
.cover.cph .cph-t{font-weight:600;display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;
 overflow:hidden;word-break:break-word}
.cover.cph .cph-c{font-size:10.5px;opacity:.55;letter-spacing:.06em;white-space:nowrap;
 overflow:hidden;text-overflow:ellipsis}
@media(max-width:700px){.cover{float:none;width:100%;max-width:260px;margin:12px 0}}
.rate{color:var(--acc);letter-spacing:2px;font-size:13px}
.idxlist{font-size:14px}
.idxlist table{width:100%;border-collapse:collapse}
.idxlist td,.idxlist th{padding:5px 8px;border-bottom:1px solid #efeae2;text-align:left;vertical-align:top;font-size:14px}
.idxlist th{color:var(--dim);font-weight:600;font-size:13px;letter-spacing:.05em}
.warn{font-size:14px;color:#5c4a2e;background:#fdf8ee;border:1px solid #ecdfc6;border-radius:8px;padding:10px 14px;margin:10px 0}
footer{margin-top:60px;border-top:1px solid var(--line);padding-top:16px;font-size:13px;color:var(--dim)}
.hidden{display:none !important}
#hitbar{font-size:13.5px;color:var(--dim);margin:6px 0 0}
header.top .bar{position:relative}
#sug{display:none;position:absolute;left:52px;right:110px;top:44px;z-index:60;max-height:64vh;
 overflow:auto;background:#fff;border:1px solid var(--line);border-radius:10px;
 box-shadow:0 12px 34px rgba(40,30,20,.16);padding:6px}
#sug.on{display:block}
#sug .sgh{font-size:11.5px;color:#a09789;letter-spacing:.1em;padding:7px 10px 3px}
#sug .sgi{display:flex;gap:9px;align-items:flex-start;padding:7px 10px;border-radius:7px;cursor:pointer}
#sug .sgi:hover,#sug .sgi.cur{background:#f7f2e9}
#sug .sgi .ic{color:var(--acc);font-size:13px;width:1.1em;flex:0 0 auto;padding-top:1px}
#sug .sgi .tx{display:block;min-width:0}
#sug .sgi .tx b{display:block;font-size:14.5px;font-weight:600;line-height:1.35;
 overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#sug .sgi .tx i{display:block;font-style:normal;font-size:12.5px;color:#8b8279;line-height:1.4}
#sug .sgi.act .ic{color:#8b8279}
.flash{animation:flash 2s ease-out 1}
@keyframes flash{0%,30%{background:#fff4d0}100%{background:transparent}}
.album.flash{outline:2px solid #e8c56a;outline-offset:3px}
tr.flash td{background:#fff4d0}
.idxgrp.flash h4{background:#fff4d0}
#nav{position:fixed;right:18px;bottom:18px;z-index:40;display:flex;flex-direction:column;
 gap:8px;align-items:flex-end}
#nav a{background:rgba(255,255,255,.96);border:1px solid var(--line);border-bottom:1px solid var(--line);
 border-radius:20px;padding:7px 14px;font-size:13px;color:#4a423a;text-decoration:none;
 box-shadow:0 2px 10px rgba(0,0,0,.07)}
#nav a:hover{background:#fff;border-color:var(--acc);color:var(--acc)}
.totoc{float:right;font-size:12.5px;color:var(--dim);border:0}
.totoc:hover{color:var(--acc);background:none}
.backrow{margin:20px 0 0;font-size:13px;text-align:right}
.tryrow{margin:12px 0 4px;font-size:13.5px;color:var(--dim)}
.try{display:inline-block;background:var(--tag);border-radius:14px;padding:1px 10px;margin:2px 3px;
 font-size:13px;color:#4a423a;cursor:pointer;border:1px solid transparent}
.try:hover{background:#efe4d4;color:var(--acc);border-color:#e0cfb8}
@media print{header.top,summary,#hitbar{display:none}.album{break-inside:avoid-page}}
"""

JS = r"""
(function(){
 var inp=document.getElementById('q'), hit=document.getElementById('hit'),
     sug=document.getElementById('sug');
 var IDX = window.__IDX || {w:[],c:[],a:[]};
 var active=-1, items=[], filterOn=false;

 function norm(s){
   s=(s||'').toLowerCase();
   s=s.replace(/[\uff01-\uff5e]/g,function(c){return String.fromCharCode(c.charCodeAt(0)-0xFEE0);});
   return s.replace(/[\s\u3000·・、,，.。:：;；!！?？'"“”‘’()（）\[\]【】《》〈〉<>\/\\|+\-_=~`@#$%^&*×—–]/g,'');
 }
 function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}

 function match(list,q,lim){
   var out=[];
   for(var i=0;i<list.length;i++){
     var it=list[i], r=-1;
     if(it._n.indexOf(q)>=0) r=0;
     else if(it._m && it._m.indexOf(q)>=0) r=1;
     else if(it._k && it._k.indexOf(q)>=0) r=2;
     if(r>=0){ it._r=r; it._o=i; out.push(it); }
   }
   out.sort(function(a,b){return a._r-b._r || a._o-b._o;});
   window.__matchCount = window.__matchCount || {};
   return out.slice(0,lim);
 }
 function prepare(){
   ['w','c','a'].forEach(function(k){
     (IDX[k]||[]).forEach(function(it){it._n=norm(it.t);it._k=norm(it.k||'');
       it._m=it.m?norm(it.m):'';});
   });
 }
 prepare();

 function go(anchor){
   var el=document.getElementById(anchor);
   if(!el) return;
   el.scrollIntoView({behavior:'smooth',block:'start'});
   el.classList.remove('flash');
   void el.offsetWidth;
   el.classList.add('flash');
   setTimeout(function(){el.classList.remove('flash');},2200);
 }

 function applyFilter(q){
   filterOn=!!q;
   var n=0;
   [].forEach.call(document.querySelectorAll('section.album'),function(sec){
     var ok=!q||norm(sec.getAttribute('data-search')).indexOf(q)>=0;
     sec.classList.toggle('hidden',!ok); if(ok)n++;
   });
   [].forEach.call(document.querySelectorAll('.toc li'),function(li){
     var ok=!q||norm(li.getAttribute('data-search')).indexOf(q)>=0;
     li.classList.toggle('hidden',!ok);
   });
   [].forEach.call(document.querySelectorAll('.toc .grp'),function(g){
     var vis=[].some.call(g.querySelectorAll('li'),function(li){return !li.classList.contains('hidden');});
     g.classList.toggle('hidden',!vis);
   });
   return n;
 }

 function render(q){
   if(!sug) return;
   if(!q){sug.classList.remove('on');sug.innerHTML='';items=[];active=-1;hit.textContent='';return;}
   var ws=match(IDX.w,q,8), cs=match(IDX.c,q,4), as=match(IDX.a,q,12);
   var nAlb=[].filter.call(IDX.a,function(it){return it._n.indexOf(q)>=0||(it._m&&it._m.indexOf(q)>=0)||(it._k&&it._k.indexOf(q)>=0);}).length;
   var nWork=[].filter.call(IDX.w,function(it){return it._n.indexOf(q)>=0||(it._k&&it._k.indexOf(q)>=0);}).length;
   var html='', n=0;
   function row(cls,anchor,main,sub,icon,extra){
     n++;
     html+='<div class="sgi'+(extra||'')+'" data-go="'+anchor+'" data-i="'+(n-1)+'">'
          +'<span class="ic">'+icon+'</span><span class="tx"><b>'+esc(main)+'</b>'
          +(sub?'<i>'+esc(sub)+'</i>':'')+'</span></div>';
   }
   if(cs.length){
     html+='<div class="sgh">作曲家</div>';
     cs.forEach(function(it){row('c',it.a,it.t,it.n+' 张唱片','◉');});
   }
   if(ws.length){
     html+='<div class="sgh">作品（跳作品索引）</div>';
     ws.forEach(function(it){row('w',it.a,it.t,(it.c||'')+' · '+it.n+' 个版本','♪');});
   }
   if(as.length){
     html+='<div class="sgh">唱片（跳具体词条）'+(nAlb>as.length?'　共 '+nAlb+' 张，先列前 '+as.length+' 张':'')+'</div>';
     as.forEach(function(it){row('a',it.a,it.t,it.m||'','▸');});
   }
   html+='<div class="sgh">操作</div>';
   html+='<div class="sgi act" data-act="filter"><span class="ic">⌕</span><span class="tx">'
        +'<b>只显示命中的唱片</b><i>共 '+nAlb+' 张；其余暂时收起</i></span></div>';
   if(filterOn){
     html+='<div class="sgi act" data-act="clear"><span class="ic">✕</span><span class="tx">'
          +'<b>取消筛选</b><i>显示全部</i></span></div>';
   }
   sug.innerHTML=html;
   sug.classList.add('on');
   items=[].slice.call(sug.querySelectorAll('.sgi'));
   active=-1;
   hit.textContent=(ws.length+cs.length+as.length)?'':'没有直接命中，可按回车在目录里筛';
 }

 function pick(el){
   if(!el) return;
   if(el.getAttribute('data-act')==='filter'){
     var n=applyFilter(norm(inp.value.trim()));
     hit.textContent='已筛出 '+n+' 张；Esc 取消';
     sug.classList.remove('on');
     return;
   }
   if(el.getAttribute('data-act')==='clear'){applyFilter('');inp.value='';render('');hit.textContent='';return;}
   var anchor=el.getAttribute('data-go');
   if(filterOn) applyFilter('');          // 跳转前先把筛选撤掉，免得目标被藏起来
   sug.classList.remove('on');
   go(anchor);
 }

 inp.addEventListener('input',function(){render(norm(inp.value.trim()));});
 inp.addEventListener('keydown',function(e){
   if(e.key==='Enter'){
     e.preventDefault();
     if(active>=0){pick(items[active]);}
     else if(items.length){pick(items[0]);}
     else{hit.textContent='筛出 '+applyFilter(norm(inp.value.trim()))+' 张；Esc 取消';}
     return;
   }
   if(e.key==='ArrowDown'||e.key==='ArrowUp'){
     if(!items.length) return;
     e.preventDefault();
     active=(active+(e.key==='ArrowDown'?1:-1)+items.length)%items.length;
     items.forEach(function(el,i){el.classList.toggle('cur',i===active);});
     items[active].scrollIntoView({block:'nearest'});
   }
 });
 document.addEventListener('click',function(e){
   var el=e.target.closest ? e.target.closest('.sgi') : null;
   if(el){pick(el);return;}
   if(sug && !sug.contains(e.target) && e.target!==inp) sug.classList.remove('on');
 });
 document.addEventListener('keydown',function(e){
   if(e.key==='/'&&document.activeElement!==inp){e.preventDefault();inp.focus();inp.select();}
   if(e.key==='Escape'){
     if(sug) sug.classList.remove('on');
     if(filterOn) applyFilter('');
     inp.value='';hit.textContent='';inp.blur();
   }
 });
 var ft=document.getElementById('ft');
 if(ft){ft.addEventListener('click',function(){
   var d=document.documentElement, on=d.classList.toggle('sans');
   ft.textContent=on?'字体：黑':'字体：宋';
 });}
 Array.prototype.forEach.call(document.querySelectorAll('[data-q]'),function(b){
   b.addEventListener('click',function(e){
     e.preventDefault();
     inp.value=b.getAttribute('data-q');
     inp.dispatchEvent(new Event('input'));
     inp.focus();
   });
 });
 document.querySelectorAll('img.cover').forEach(function(im){
   im.addEventListener('error',function(){im.style.display='none';});
 });
})();
"""


def pick_cover(al):
    """在专辑目录里找一张封面图"""
    arts = [a for a in al.get('art', []) if a['size'] > 8000]
    if not arts:
        return None
    pref = ['cover', 'front', 'folder', '01', '封面', 'f']
    for p in pref:
        for a in arts:
            base = os.path.splitext(os.path.basename(a['path']).lower())[0]
            if base == p or base.startswith(p):
                return a['path']
    # 取分辨率/体积最大的
    return max(arts, key=lambda x: x['size'])['path']


CN_DIGIT = {'0': '零', '1': '一', '2': '二', '3': '三', '4': '四', '5': '五',
            '6': '六', '7': '七', '8': '八', '9': '九', '10': '十',
            '11': '十一', '12': '十二', '13': '十三', '14': '十四', '15': '十五'}

COMPOSER_ABBR = [
    ('贝多芬', '贝'), ('莫扎特', '莫'), ('舒伯特', '舒'), ('肖斯塔科维奇', '肖'),
    ('柴可夫斯基', '柴'), ('拉赫玛尼诺夫', '拉'), ('德沃夏克', '德'), ('斯美塔那', '斯'),
    ('小约翰', '施'), ('老约翰', '施'), ('理查', '理'), ('施特劳斯', '施'),
    ('哈恰图良', '哈'), ('霍尔斯特', '霍'), ('维瓦尔第', '维'), ('罗西尼', '罗'),
    ('苏佩', '苏'), ('瓦格纳', '瓦'), ('门德尔松', '门'), ('斯克里亚宾', '斯'),
    ('勃拉姆斯', '勃'), ('巴赫', '巴'), ('海顿', '海'), ('何占豪', '何'), ('陈钢', '陈'),
]

GENRE_WORDS = [
    ('钢琴协奏曲', '钢协', ['piano concerto']),
    ('小提琴协奏曲', '小协', ['violin concerto']),
    ('协奏曲', '协', ['concerto']),
    ('交响曲', '交', ['symphony', 'symphonie']),
    ('奏鸣曲', '奏', ['sonata']),
    ('小夜曲', '夜', ['serenade']),
    ('嬉游曲', '嬉', ['divertimento']),
    ('组曲', '组', ['suite']),
    ('交响诗', '诗', ['tone poem']),
    ('序曲', '序', ['overture']),
    ('弥撒', '弥', ['mass']),
    ('变奏曲', '变', ['variations']),
    ('圆舞曲', '圆', ['waltz']),
    ('波尔卡', '波', ['polka']),
    ('进行曲', '进', ['march']),
    ('芭蕾', '芭', ['ballet']),
    ('四重奏', '四', ['quartet']),
]

ALIASES = {'works': {}, 'albums': {}}


def load_aliases():
    p = os.path.join(KN, '_aliases.json')
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding='utf-8-sig'))
            ALIASES['works'] = d.get('works') or {}
            ALIASES['albums'] = d.get('albums') or {}
        except Exception as e:
            print('  !! _aliases.json 读取失败:', e)


def composer_abbr(comp):
    for k, v in COMPOSER_ABBR:
        if k in (comp or ''):
            return v
    return ''


def work_numbers(w):
    """从作品标题里抽 (体裁, 编号, opus, k 号)"""
    txt = ' '.join(filter(None, [w.get('title'), w.get('id'), ' '.join(w.get('aka') or [])]))
    genre = ''
    for g, short, en in GENRE_WORDS:
        if g in txt:
            genre = g
            break
    if not genre:
        for g, short, en in GENRE_WORDS:
            if any(e in txt.lower() for e in en):
                genre = g
                break
    num = ''
    m = re.search(r'第\s*([一二三四五六七八九十]{1,3})\s*(?:交响曲|钢琴协奏曲|协奏曲|奏鸣曲|组曲|小夜曲)', txt)
    if m:
        num = m.group(1)
    if not num:
        m = re.search(r'\bno\.?\s*(\d{1,2})\b', txt, re.I)
        if m:
            num = m.group(1)
    opus = re.search(r'op(?:us)?\.?\s*(\d{1,4})', txt, re.I)
    kv = re.search(r'\bKV?\.?\s*(\d{1,4})', txt)
    return genre, num, (opus.group(1) if opus else ''), (kv.group(1) if kv else '')


CN_TO_INT = {v: k for k, v in CN_DIGIT.items()}


def auto_aliases(w):
    """按作品标题派生搜索词：贝九 / 贝5 / op67 / k334 / symphony 9 …"""
    out = set(w.get('aka') or [])
    comp_cn = (w.get('composer') or '').split(' ')[0]
    abbr = composer_abbr(w.get('composer') or '')
    genre, num, opus, kv = work_numbers(w)
    short = next((s for g, s, e in GENRE_WORDS if g == genre), '')
    # 编号统一成「阿拉伯数字」与「中文数字」两套
    cn = num if not str(num).isdigit() else CN_DIGIT.get(str(num), '')
    ar = str(num) if str(num).isdigit() else CN_TO_INT.get(str(num), '')
    if num:
        if abbr:
            out.add(f'{abbr}{cn or ar}')
            if short:
                out.add(f'{abbr}{cn or ar}{short}')
            if ar and ar != cn:
                out.add(f'{abbr}{ar}')
        if comp_cn:
            out.add(f'{comp_cn}{ar or cn}')
            out.add(f'{comp_cn}第{cn or ar}{genre}' if genre else f'{comp_cn}{ar or cn}')
        for g, s2, en in GENRE_WORDS:
            if g == genre:
                for e in en:
                    out.add(f'{e} {ar or num}')
                    out.add(f'{e} no {ar or num}')
                    out.add(f'{e} no. {ar or num}')
                break
        m = re.search(r'([A-Z][A-Za-z\-]{3,})', (w.get('composer') or ''))
        if m:
            out.add(f'{m.group(1).lower()} {ar or num}')
    if opus:
        for f in ('op', 'op.', 'opus', 'opus '):
            out.add(f'{f}{opus}')
    if kv:
        for f in ('k', 'k.', 'kv', 'kv '):
            out.add(f'{f}{kv}')
    t = re.sub(r'[《》「」“”\'\"]', '', w.get('title') or '')
    if t:
        out.add(t)
    out |= set(ALIASES['works'].get(w.get('_id') or '', []) or [])
    return sorted({x.strip() for x in out if x and x.strip() and len(x) <= 40})


def album_search_blob(al, kn, works, wmap, work_index_all=None):
    """一张专辑的搜索语料：元信息 + 全部曲名 + 命中的作品与别名 + 乐章名"""
    kn = kn or {}
    parts = [al['name'], kn.get('composer', ''), kn.get('performer', ''), kn.get('label', ''),
             kn.get('edition', ''), kn.get('oneliner', ''), kn.get('recorded', ''),
             kn.get('released', ''), ' '.join(kn.get('tags') or []),
             ' '.join(ALIASES['albums'].get(al['name'], []) or [])]
    for d in al['discs']:
        parts.append(d.get('label') or '')
    for t in al['tracks']:
        parts.append(t.get('title') or '')
        parts.append(t.get('performer') or '')
    parts.extend(kn.get('track_notes', {}).keys() if isinstance(kn.get('track_notes'), dict) else [])
    seen = set()
    for g in group_tracks(works, al['tracks'], flatten_hints(kn.get('track_works'), al['discs']),
                          wmap, composer_key(kn.get('composer', ''))):
        w = g['work']
        if not w or w['_id'] in seen:
            continue
        seen.add(w['_id'])
        parts.append(w.get('title') or '')
        parts.extend(w.get('_aliases') or [])
        for mv in w['_mv']:
            parts.append(mv.get('name') or '')
    return ' '.join(p for p in parts if p)


COMPOSER_RANK_WORDS = [
    ('贝多芬', 1), ('莫扎特', 2), ('舒伯特', 3), ('肖斯塔科维奇', 4),
    ('理查', 5), ('小约翰', 6), ('老约翰', 7), ('施特劳斯', 8),
    ('柴可夫斯基', 9), ('拉赫玛尼诺夫', 10), ('德沃夏克', 11), ('斯美塔那', 12),
    ('斯克里亚宾', 13), ('霍尔斯特', 14), ('维瓦尔第', 15), ('哈恰图良', 16),
    ('门德尔松', 17), ('罗西尼', 18), ('苏佩', 19), ('瓦格纳', 20),
    ('比才', 21), ('李斯特', 22), ('帕赫贝尔', 23), ('巴赫', 24),
]
GENRE_RANK = {'交响曲': 1, '协奏曲': 2, '奏鸣曲': 3, '组曲': 4, '芭蕾': 4,
              '序曲': 5, '交响诗': 6, '弥撒': 7, '清唱剧': 7,
              '变奏曲': 8, '幻想曲': 8, '歌曲': 9, '四重奏': 10,
              '小夜曲': 11, '嬉游曲': 12, '圆舞曲': 13, '波尔卡': 14, '进行曲': 15}


def composer_rank(comp):
    for k, r in COMPOSER_RANK_WORDS:
        if k in (comp or ''):
            return r
    return 60


def work_sort_key(w):
    """索引排序：作曲家 → 体裁 → 作品编号 → Op./K. → 标题"""
    genre, num, opus, kv = work_numbers(w)
    n = None
    if num:
        if str(num).isdigit():
            n = int(num)
        else:
            v = CN_TO_INT.get(str(num))
            n = int(v) if str(v or '').isdigit() else None
    return (composer_rank(w.get('composer')),
            GENRE_RANK.get(genre, 50),
            n if n else 999,
            int(opus) if str(opus).isdigit() else 999,
            int(kv) if str(kv).isdigit() else 999,
            w.get('title') or '')


G_COVERS = {}


def _resize_cover(src, dst, maxedge, quality=82):
    from PIL import Image
    im = Image.open(src)
    if im.mode not in ('RGB', 'L'):
        im = im.convert('RGB')
    im.thumbnail((maxedge, maxedge), Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst, 'JPEG', quality=quality, optimize=True, progressive=True)


def export_covers(albums):
    """封面从音乐库取出来压成两张（1000px 大图 + 420px 缩略图）放进站点目录。
    返回 {专辑名: (缩略图相对路径, 大图相对路径)}"""
    os.makedirs(COVERS, exist_ok=True)
    os.makedirs(COVERS_T, exist_ok=True)
    out = {}
    for al in albums:
        if not ROOT:
            return {}
        rel = pick_cover(al)
        if not rel:
            continue
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            continue
        key = hashlib.md5(al['name'].encode('utf-8')).hexdigest()[:12]
        big = os.path.join(COVERS, key + '.jpg')
        thumb = os.path.join(COVERS_T, key + '.jpg')
        try:
            if not os.path.exists(big) or os.path.getmtime(big) < os.path.getmtime(src):
                _resize_cover(src, big, 1000)
                _resize_cover(src, thumb, 420)
        except Exception as e:
            print('  !! 封面处理失败', al['name'][:28], type(e).__name__)
            continue
        out[al['name']] = ('assets/covers/t/%s.jpg' % key, 'assets/covers/%s.jpg' % key)
    return out


def short_perf(kn, name=''):
    """版本索引里用的短标签：指挥/演奏者 + 乐团，最多 18 字"""
    p = (kn.get('performer') or '').strip()
    if not p:
        return name[:18]
    for sep in ('；', ';', ' / ', '（', '('):
        if sep in p:
            p = p.split(sep)[0]
    p = p.strip()
    # 只留姓氏 + 乐团：取「/」后的乐团名
    return p[:18] + ('…' if len(p) > 18 else '')


G_ALBUMS = []
G_SAME = {}
G_KN = {}


def same_source_map(albums):
    """自动找「同一录音的不同抓取/转制」：把两两专辑的时长排序后做容差对齐，
    重合比例很高就说明是一致的录音（曲名可能被改写过，时长骗不了人）。"""
    dur = []
    for a in albums:
        dur.append(sorted(float(t['duration']) for t in a['tracks'] if t.get('duration')))
    out = {}
    n = len(albums)
    for i in range(n):
        li = dur[i]
        if len(li) < 5:
            continue
        for j in range(i + 1, n):
            lj = dur[j]
            if len(lj) < 5:
                continue
            if min(len(li), len(lj)) / max(len(li), len(lj)) < 0.6:
                continue
            pi = pj = hit = 0
            while pi < len(li) and pj < len(lj):
                d = li[pi] - lj[pj]
                if abs(d) <= 1.5:
                    hit += 1
                    pi += 1
                    pj += 1
                elif d < 0:
                    pi += 1
                else:
                    pj += 1
            ratio = hit / min(len(li), len(lj))
            if ratio >= 0.85:
                out.setdefault(i, []).append((j, round(ratio, 2)))
                out.setdefault(j, []).append((i, round(ratio, 2)))
    return out


FMT_TAG_RE = re.compile(r'\s*\[(?:16|24|32)[-/](?:44|48|88|96|176|192|384)[^\]]*\]', re.I)


def display_name(n):
    """给页面看的标题：去掉文件式的下划线前缀与 [24-96] 这类格式标签"""
    t = re.sub(r'^_+', '', n or '')
    t = FMT_TAG_RE.sub('', t)
    t = re.sub(r'\s{2,}', ' ', t).strip(' -')
    return t or (n or '')


def disp(name, kn=None):
    """页面标题：知识库给了 title_display 就用它，否则净化文件名"""
    t = (kn or {}).get('title_display')
    return t.strip() if isinstance(t, str) and t.strip() else display_name(name)


def short_album(name, n=26):
    """去掉作曲家前缀与尾部括注，留下能区分这一版的短名"""
    t = name or ''
    if ' - ' in t:
        t = t.split(' - ', 1)[1]
    t = t.strip()
    return t[:n] + ('…' if len(t) > n else '')


def render_tags(kn):
    out = []
    for t in (kn.get('tags') or [])[:4]:
        out.append(f'<span class="tag">{esc(t)}</span>')
    return ''.join(out)


def stars(r):
    try:
        r = int(r)
    except Exception:
        return ''
    r = max(0, min(5, r))
    return '<span class="rate">' + '★' * r + '☆' * (5 - r) + '</span>'


def render_album(idx, al, kn, works, album_order, work_index, wmap=None):
    name = al['name']
    st = al['stats']
    kn = kn or {}
    tw = kn.get('track_works') or []
    pref = composer_key(kn.get('composer', ''))
    anchor = find_work(works, name, pref)
    # track_works 允许两种写法：全专辑平铺一维数组；或每个碟一个子数组
    tw_per_disc = bool(tw) and isinstance(tw[0], list)
    tags = render_tags(kn)
    chips = []
    if kn.get('performer'):
        chips.append(f'<span class="chip">{esc(kn["performer"])}</span>')
    rec = kn.get('recorded') or ''
    rel = kn.get('released') or ''
    if rec or rel:
        chips.append(f'<span class="chip k">录音 {esc(rec)}' + (f' · 本版 {esc(rel)}' if rel else '') + '</span>')
    if kn.get('label'):
        chips.append(f'<span class="chip k">{esc(kn["label"])}</span>')
    if kn.get('edition'):
        chips.append(f'<span class="chip k">{esc(kn["edition"])}</span>')
    tail = (f'{st["n_tracks"]} 轨' + (f' · {fmt_dur_cn(st["duration"])}' if st['duration'] else '')) if st['n_tracks'] else '整盘镜像'
    if not PUBLIC:
        specs = sorted(st['specs'].items(), key=lambda kv: -kv[1])
        spec_txt = '；'.join(f'{k}×{v}' for k, v in specs[:3]) if specs else '（无音频文件）'
        chips.append(f'<span class="chip">{esc(spec_txt)}</span>')
        tail += f' · {fmt_size(st["size"])}'
    chips.append(f'<span class="chip k">{esc(tail)}</span>')

    h = []
    w = h.append
    blob = album_search_blob(al, kn, works, wmap)
    w(f'<section class="album" id="{aid(name)}" data-search="{esc(blob)}">')
    w(f'<div class="num">专辑 {idx:02d}　·　{esc((kn.get("composer") or "") or "")}'
      f'<a class="totoc" href="#toc">↑ 目录</a></div>')
    w(f'<h2 class="title">{esc(disp(name, kn))} {tags} {stars(kn.get("rating"))}</h2>')
    cv = G_COVERS.get(name)
    if cv:
        w(f'<a href="{esc(cv[1])}" target="_blank"><img class="cover" loading="lazy" '
          f'alt="封面" src="{esc(cv[0])}"></a>')
    else:
        # 没有封面时用纯排版占位：一条按作曲家取色的「书脊」，不引用任何图片
        hue = int(hashlib.md5((kn.get('composer') or name).encode('utf-8')).hexdigest()[:2], 16) % 360
        comp = (kn.get('composer') or '').split(' ')[0]
        w(f'<div class="cover cph" style="--h:{hue}" aria-hidden="true">'
          f'<span class="cph-n">NO.{idx:02d}</span>'
          f'<span class="cph-t">{esc(short_album(disp(name, kn), 60))}</span>'
          f'<span class="cph-c">{esc(comp)}</span></div>')
    w('<div class="chips">' + ''.join(chips) + '</div>')
    if kn.get('oneliner'):
        w(f'<div class="oneliner">{esc(kn["oneliner"])}</div>')
    for nb in (kn.get('version_notes') or []):
        if not (nb.get('t') or '').strip():
            continue
        w(f'<div class="note"><h5>{esc(nb.get("h") or "说明")}</h5><p>{esc(nb.get("t"))}</p></div>')

    # 同源提示（曲名+时长逐轨吻合）
    twins = G_SAME.get(idx - 1) or []
    if twins:
        links = '、'.join(f'<a href="#{aid(G_ALBUMS[j]["name"])}" title="{esc(display_name(G_ALBUMS[j]["name"]))}">{j + 1:02d}·{esc(short_album(display_name(G_ALBUMS[j]["name"])))}</a>'
                          for j, _r in twins[:4])
        w(f'<div class="cmp"><b>同源</b>：这一张与 {links} 的曲目、时长逐轨吻合，'
          f'应是同一录音的不同转制（不是两次不同的演绎）。</div>')

    # 同曲多版本对照（只列库内还有别的版本的作品）
    flat_tw = flatten_hints(tw, al['discs'])
    mine = []
    seen = set()
    for g in group_tracks(works, al['tracks'], flat_tw, wmap, pref, anchor):
        if g['work'] and g['work']['_id'] not in seen:
            seen.add(g['work']['_id'])
            mine.append(g['work'])
    parts = []
    only_here = 0
    for wk in mine:
        others = [album_order[k] for k in work_index.get(wk['_id'], []) if album_order[k][0] != name]
        if not others:
            only_here += 1
            continue
        links = '、'.join(f'<a href="#{aid(n)}" title="{esc(display_name(n))}">{esc(short_album(display_name(n)))}</a>' for n, _i in others[:4])
        parts.append(f'<b>{esc(wk.get("title"))}</b>：另有 {len(others)} 版（{links}）')
    if parts:
        more = '' if len(parts) <= 6 else f'　…另有 {len(parts) - 6} 部作品在库内也有别的版本'
        w('<div class="cmp"><b style="display:block;margin-bottom:4px">同一部作品的其它录音</b>'
          + '<br>'.join(parts[:6]) + more + '</div>')
    elif mine and only_here:
        w('<div class="cmp">这张唱片里的作品，在库内都只有这一版。</div>')

    # 曲目
    if al['discs']:
        w('<h3 id="toc_' + aid(name) + '">曲目</h3>')
    off = 0
    for di, d in enumerate(al['discs'], 1):
        if len(al['discs']) > 1:
            _lab = display_name((d.get('label') or '').replace(name, disp(name, kn)))
            w(f'<h4>碟 {di} · {esc(_lab)}' + (f'　{fmt_dur(d.get("duration"))}' if d.get('duration') else '') + '</h4>')
        if not tw:
            dh = None
        elif tw_per_disc:
            dh = tw[di - 1] if di - 1 < len(tw) else None
        else:
            dh = tw[off:off + len(d['tracks'])]
        off += len(d['tracks'])
        groups = group_tracks(works, d['tracks'], dh, wmap, pref, anchor)
        if d.get('iso_disc'):
            # 镜像/蓝光碟：曲目可能来自碟内元数据、知识库补录，或按名字推断
            srcs = {(t.get('tags') or {}).get('src') for t in d['tracks']}
            if 'meta' in srcs:
                note = '曲目来自碟内元数据，时长与碟面标示一致。'
            elif 'kn' in srcs:
                note = '曲目按这张唱片的内容补录。'
            else:
                note = '这张唱片没有可解析的分轨信息，曲目是按唱片标示推断出来的（能确认的才列）。'
            w(f'<p class="arcnote">{note}</p>')
        if d.get('image') and not PUBLIC:
            w(f'<p class="files">整碟镜像：<code>{esc(d.get("image_path"))}</code> · {fmt_size(d.get("image_size"))}'
              + (f' · CUE：<code>{esc(os.path.basename(d.get("cue","")))}</code>' if d.get('cue') else '') + '</p>')
        # 整碟镜像在公开版里不额外说明，曲目照列即可
        for g in groups:
            wk = g['work']
            if wk:
                w('<div class="workbox">')
                who = ''
                if wk.get('composer'):
                    who = f'<span class="who">{esc(wk.get("composer"))}</span>'
                w(f'<div class="workhead">{esc(wk.get("title"))}{who}</div>')
                if wk.get('about'):
                    w(f'<div class="workabout">{esc(wk["about"])}</div>')
                w('<table class="tracks">')
                for t in g['tracks']:
                    mv = t.get('_mv')
                    ti = t.get('title') or ''
                    if mv and mv.get('name'):
                        ti = f'{esc(mv.get("name"))}'
                        if mv.get('n'):
                            ti = f'<span style="color:#a09789">乐章 {esc(str(mv.get("n")))}</span>　' + ti
                    else:
                        if t.get('inferred') and len(ti) > 78:
                            ti = esc(ti[:76]) + '…'
                        else:
                            ti = esc(ti)
                    _cls = 'mv inf' if t.get('inferred') else 'mv'
                    w(f'<tr class="{_cls}"><td class="no">{esc(t.get("no"))}</td><td class="ti">{ti}</td>'
                      f'<td class="du">{fmt_dur(t.get("duration"))}</td></tr>')
                    if mv and mv.get('about'):
                        w(f'<tr class="about"><td></td><td colspan="2">{esc(mv["about"])}</td></tr>')
                    elif t.get('performer'):
                        w(f'<tr class="about"><td></td><td colspan="2"><span style="color:#8b8279;font-size:12.5px">{esc(t["performer"])}</span></td></tr>')
                w('</table></div>')
            else:
                # 非套曲：逐轨 + track_notes
                notes = kn.get('track_notes') or {}
                w('<div class="workbox"><table class="tracks">')
                for t in g['tracks']:
                    nt = notes.get(t.get('title') or '') or notes.get(str(t.get('no'))) or ''
                    _cls = 'mv inf' if t.get('inferred') else 'mv'
                    w(f'<tr class="{_cls}"><td class="no">{esc(t.get("no"))}</td>'
                      f'<td class="ti">{esc(t.get("title"))}'
                      + (f'<span style="color:#8b8279;font-size:12.5px"> — {esc(t.get("performer"))}</span>' if t.get('performer') and not nt else '')
                      + f'</td><td class="du">{fmt_dur(t.get("duration"))}</td></tr>')
                    if nt:
                        w(f'<tr class="about"><td></td><td colspan="2">{esc(nt)}</td></tr>')
                w('</table></div>')

    # 影像 / 蓝光
    vids = al.get('video') or []
    if vids and PUBLIC:
        w(f'<p class="files">影像资料：{len(vids)} 段。</p>')
        vids = []
    if vids:
        w('<h4>影像与蓝光载体</h4><div class="files">')
        for v in sorted(vids, key=lambda x: -x['size'])[:12]:
            pr = v.get('probe') or {}
            line = f'<div style="margin:3px 0"><code>{esc(v["name"])}</code> · {fmt_size(v["size"])}'
            if pr.get('duration'):
                line += f' · 时长 {fmt_dur(pr["duration"])}'
            if pr.get('audio'):
                line += ' · ' + esc(' / '.join(pr['audio'][:2]))
            line += '</div>'
            w(line)
        if len(vids) > 12:
            w(f'<div>…共 {len(vids)} 个流文件</div>')
        w('</div>')

    # 文件清单（公开版不输出）
    if PUBLIC:
        w('<p class="backrow"><a href="#toc">↑ 回到目录</a>　·　<a href="#top">回到顶部</a></p>')
        w('</section>')
        return '\n'.join(h)
    w('<details><summary>文件清单与磁盘占用</summary><div class="files">')
    w(f'<p>目录：<code>{esc(name)}</code>　音频 {st["n_audio"]} 个 / 碟 {st["n_discs"]} 张'
      f' / 图片 {st["n_art"]} / 文档 {st["n_doc"]}'
      + (f' / 镜像 {st["n_iso"]}' if st['n_iso'] else '')
      + (f' / 影像 {st["n_video"]}' if st['n_video'] else '')
      + (f' / 残留备份 {st["n_junk"]}' if st['n_junk'] else '') + '</p>')
    if st['n_junk']:
        w('<p>杂项：' + '、'.join(f'<code>{esc(x["name"])}</code>' for x in al['junk'][:10]) + '</p>')
    if al['doc']:
        docs = [x for x in al['doc'] if os.path.splitext(x['name'])[1].lower() in ('.pdf', '.txt', '.m3u')]
        if docs:
            w('<p>随碟文档：' + '、'.join(f'<code>{esc(x["name"])}</code>' for x in docs[:12]) + '</p>')
    w('</div></details>')
    w('<p class="backrow"><a href="#toc">↑ 回到目录</a>　·　<a href="#top">回到顶部</a></p>')
    w('</section>')
    return '\n'.join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--note', default='')
    ap.add_argument('--dev', action='store_true', help='开发模式：写 _dev.html，不升版本、不归档、不写日志')
    ap.add_argument('--local', action='store_true',
                    help='本机版：恢复「文件清单 / 磁盘占用 / 残留文件」等本机信息')
    ap.add_argument('--covers', action='store_true',
                    help='导出封面到 docs/assets/covers（封面是唱片公司的版权素材，公开仓库默认不带）')
    ap.add_argument('--no-covers', action='store_true', help='（兼容旧命令，等同默认行为）')
    args = ap.parse_args()
    global PUBLIC
    PUBLIC = not args.local

    inv = json.load(open(os.path.join(DATA, 'inventory.json'), encoding='utf-8'))
    kn_albums, works, works_map, loose_kn, conflicts = load_knowledge()

    albums = inv['albums']
    global G_COVERS
    if args.covers and not args.no_covers:
        G_COVERS = export_covers(albums)
        print(f'  封面导出 {len(G_COVERS)} 张 -> docs/assets/covers（注意版权）')
    else:
        print('  封面：未导出（页面用排版占位，仓库里不含任何图片）')
    os.makedirs(SITE, exist_ok=True)
    open(os.path.join(SITE, '.nojekyll'), 'w').close()
    # 知识库可以用 arc_tracks 指定「镜像/蓝光里到底有哪些作品」
    for al in albums:
        kn0 = kn_albums.get(al['name']) or {}
        arc = kn0.get('arc_tracks')
        if not arc:
            continue
        for d in al['discs']:
            if d.get('iso_disc'):
                d['tracks'] = [{'no': i, 'title': t, 'performer': '', 'duration': None,
                                'spec': '镜像/蓝光内曲目', 'tags': {'src': 'kn'},
                                'image': False, 'inferred': True}
                               for i, t in enumerate(arc, 1)]
        al['tracks'] = [t for d in al['discs'] for t in d['tracks']]
        specs = {}
        for t in al['tracks']:
            sp = t.get('spec') or ''
            if sp:
                specs[sp] = specs.get(sp, 0) + 1
        al['stats']['n_tracks'] = len(al['tracks'])
        al['stats']['specs'] = specs
    album_order = [(a['name'], i) for i, a in enumerate(albums)]
    global G_ALBUMS, G_SAME, G_KN
    G_ALBUMS = albums
    G_KN = kn_albums
    G_SAME = same_source_map(albums)

    # 分类
    cats = {}
    for i, al in enumerate(albums):
        kn = kn_albums.get(al['name'])
        key, label = classify(al, kn)
        if al['kind'] == 'empty' and al['name'] in ('[_DVD]', '[_解释]'):
            key, label = 'av', '影像 · 镜像'
        cats.setdefault(key, {'label': label, 'items': []})['items'].append((i, al))

    # 作品索引
    work_index = {}
    for i, al in enumerate(albums):
        seen = set()
        kn = kn_albums.get(al['name']) or {}
        _pref = composer_key(kn.get('composer', ''))
        _anc = find_work(works, al['name'], _pref)
        for g in group_tracks(works, al['tracks'], flatten_hints(kn.get('track_works'), al['discs']),
                               works_map, _pref, _anc):
            if g['work']:
                wid = g['work']['_id']
                if wid not in seen:
                    seen.add(wid)
                    work_index.setdefault(wid, []).append(i)

    order_keys = [c[0] for c in CATS]
    cat_seq = {k: n for n, k in enumerate(order_keys)}

    # ---------- 统计
    tot_tracks = sum(a['stats']['n_tracks'] for a in albums)
    tot_dur = sum(a['stats']['duration'] for a in albums)
    tot_size = sum(a['stats']['size'] for a in albums)
    spec_tot = {}
    for a in albums:
        for k, v in a['stats']['specs'].items():
            spec_tot[k] = spec_tot.get(k, 0) + v
    have_notes = sum(1 for a in albums if kn_albums.get(a['name'], {}).get('version_notes'))
    mv_total = sum(len(w['_mv']) for w in works)
    matched_mv = 0
    matched_tracks = 0
    for a in albums:
        kn = kn_albums.get(a['name']) or {}
        _pref = composer_key(kn.get('composer', ''))
        _anc = find_work(works, a['name'], _pref)
        for g in group_tracks(works, a['tracks'], flatten_hints(kn.get('track_works'), a['discs']),
                              works_map, _pref, _anc):
            if g['work']:
                matched_tracks += len(g['tracks'])
                matched_mv += sum(1 for t in g['tracks'] if t.get('_mv'))

    state = load_state()
    ver = 0 if args.dev else state.get('version', 0) + 1
    now = time.localtime()
    now_s = time.strftime('%Y-%m-%d %H:%M', now)

    # ---------- 变更检测
    new_fp = {a['name']: fingerprint(a) for a in albums}
    old_fp = state.get('albums', {})
    added = [n for n in new_fp if n not in old_fp]
    removed = [n for n in old_fp if n not in new_fp]
    changed = [n for n in new_fp if n in old_fp and old_fp[n] != new_fp[n]]

    favicon_uri = favicon(PUBLIC)
    mark_bar = svg_mark(26, cls='mk') if LOGO_MODE in ('both', 'bar') else ''
    mark_mast = svg_mark(66, cls='mk') if LOGO_MODE in ('both', 'mast') else ''
    H = []
    w = H.append
    w('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    w('<meta name="viewport" content="width=device-width,initial-scale=1">')
    w(f'<link rel="icon" type="image/svg+xml" href="{favicon_uri}">')
    w(f'<title>音乐库目录 v{ver} · {len(albums)} 张</title>')
    w(f'<style>{CSS}</style></head><body id="top">')
    w('<header class="top"><div class="bar">'
      f'<a class="brand" href="#top" title="回到顶部">{mark_bar}<b>音乐库目录</b></a>'
      '<input id="q" type="search" placeholder="搜索：作曲家 / 曲名 / 指挥 / 版本关键词…（按 / 聚焦）" autocomplete="off">'
      '<button class="ftbtn" id="ft" type="button" title="切换衬线（宋）/ 无衬线（雅黑）">字体：宋</button>'
      '<span class="hint" id="hit"></span><div id="sug"></div></div></header>'
      '<nav id="nav"><a href="#toc" title="回到分类目录">↑ 目录</a>'
      '<a href="#top" title="回到文件开头">↑ 顶部</a></nav><div class="wrap">')

    # 封面区
    w(f'<div class="mast">{mark_mast}<h1>音乐库目录</h1></div>')
    w(f'<div class="sub">版本 <b>v{ver}</b>　·　生成于 {now_s}'
      f'　·　<a href="#changelog">更新记录</a>　·　<a href="#appendix">附录</a></div>')
    w('<div class="cards">')
    n_comp = len({(kn_albums.get(a['name']) or {}).get('composer') for a in albums} - {None, ''})
    for k, v, s in [('唱片 / 版本', len(albums), f'{n_comp} 位作曲家'),
                    ('音轨总数', tot_tracks, f'{len(works)} 部作品已建条目'),
                    ('总时长', f'{int(tot_dur // 3600)} 小时', f'{int(tot_dur % 3600 // 60)} 分'),
                    ('作品 / 乐章', len(works), f'乐章级 {mv_total} 条'),
                    ('逐曲讲解', f'{matched_tracks}', f'另有 {sum(len(v.get("track_notes") or {}) for v in kn_albums.values())} 条歌曲注释')]:
        w(f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>')
    w('</div>')
    if not PUBLIC:
        w('<p class="s" style="font-size:13px;color:#6b635b">规格分布：' +
          '；'.join(f'{k} <b>{v}</b>' for k, v in sorted(spec_tot.items(), key=lambda kv: -kv[1])[:6]) + '</p>')

    # 怎么用
    w('<h2 id="howto">怎么用这本目录</h2>')
    w('<p>按分类看「<a href="#toc">目录</a>」；想比对同一部作品的不同录音，看「<a href="#workindex">作品索引</a>」；'
      '想查某张唱片到底值不值得听，直接点进单张的「版本详解」。'
      '顶上的搜索框会给一份<b>推荐清单</b>：搜作曲家或作品（贝多芬、贝九、K.334）先给「作品 / 作曲家」，'
      '回车直接跳到作品索引那一行；搜指挥、乐团、年份、版本关键词（Kempff、1963、SACD）先给「唱片」，跳到那一张。'
      '上下键选，回车确认；想按命中筛选整本目录，选「只显示命中的唱片」。'
      '绰号与简称也认（见下），英文、俄文照打即可。右下角常驻「↑ 目录 / ↑ 顶部」，读完一张不用往回找。</p>')
    w('<p class="tryrow">试试这些词：'
      + ''.join(f'<button class="try" type="button" data-q="{q}">{esc(q)}</button>'
                for q in ['贝九', '命运', '皇帝', '贝五钢协', 'K.334', '嬉游曲', '四季', '行星',
                          '梁祝', '肖七', '列宁格勒', '柴一', '拉二', 'op67', 'symphony 9',
                          'Группа крови', '蔡琴', '惠威']) + '</p>')
    w('<p>每张唱片一节，固定结构：<b>元信息 → 一句话定位 → 版本详解（录音与阵容 / 版本与转制 / 听感与特色 / 收藏与使用）'
      '→ 同曲对照 → 曲目与逐曲讲解</b>。曲目按作品分组，同一部作品的所有乐章连在一起，'
      '作品说明在组头，乐章讲解跟在每一轨下面。</p>')
    if not PUBLIC:
        w('<p>每节右上角是封面位：<b>本仓库不收录唱片封面</b>（那是唱片公司的版权素材），'
          '改用一条按作曲家取色的排版书脊占位；在本地想看图可以 <code>python build.py --covers</code>，'
          '但别把生成出来的 <code>docs/assets</code> 推上公开仓库。'
          '章节锚点用专辑名的哈希，所以这份文件重新生成后，旧的链接依然有效。</p>')

    if not PUBLIC:
        w('<details style="margin:16px 0 0"><summary>这本目录是怎么生成的 / 以后怎么更新</summary>'
        '<div class="files" style="font-size:13.5px;line-height:1.8">'
        '<p>全部由 <code>tools\\</code> 下的脚本生成，内容与排版分离：</p>'
        '<p>1. <code>scan.py</code> 扫一遍音乐库，只读文件头，产出 <code>_data\\inventory.json</code>（专辑 / 碟 / 轨、时长、采样规格、CUE、镜像、杂项）。</p>'
        '<p>2. <code>_data\\knowledge\\*.json</code> 是讲解内容（版本详解、作品与乐章说明、曲目注释），'
        '按作曲家分组，一人一个文件，格式见 <code>_SCHEMA.md</code>。改这里就是在改书的内容。</p>'
        '<p>3. <code>build.py</code> 把两者合并成这一份 HTML，升版本号、把上一版整份挪进 <code>archive\\</code>、'
        '并在 <code>更新日志.md</code> 记下这一版改了什么。</p>'
        '<p>日常更新只有两步：音乐库加了新唱片就重跑 <code>scan.py</code>，然后 '
        '<code>python build.py --note "加了某某"</code>。旧版永远留在 <code>archive\\</code> 里，不会丢。</p>'
        '</div></details>')

    # 目录
    w('<h2 id="toc">目录</h2><div class="toc">')
    for key in sorted(cats.keys(), key=lambda k: cat_seq.get(k, 99)):
        c = cats[key]
        w(f'<div class="grp" id="cat-{key}"><div class="gh">{esc(c["label"])}　<span style="font-weight:400">{len(c["items"])}</span></div><ol>')
        for i, al in sorted(c['items'], key=lambda x: x[0]):
            kn = kn_albums.get(al['name'], {})
            st = al['stats']
            desc = kn.get('oneliner') or ''
            meta = ' · '.join(filter(None, [kn.get('performer', ''), fmt_dur_cn(st['duration']) if st['duration'] else '',
                                            f'{st["n_tracks"]} 轨' if st['n_tracks'] else '']))
            srch = esc(album_search_blob(al, kn, works, works_map))
            w(f'<li data-search="{srch}"><span class="n">{i + 1:02d}</span>'
              f'<a href="#{aid(al["name"])}">{esc(disp(al["name"], kn))}</a>'
              f'<span class="d">{esc(desc) if desc else "（暂无讲解，见正文）"}</span></li>')
        w('</ol></div>')
    w('</div>')

    # 作品索引
    w('<h2 id="workindex">作品索引（同一部作品的全部录音）</h2>')
    w('<p>这一节回答「这部曲子我收了几个版本、各是谁的」——点进去看逐版的版本详解。</p>')
    by_comp = {}
    for wid, idxs in work_index.items():
        wk = works_map[wid]
        by_comp.setdefault(wk.get('composer') or '其他', []).append((wk, idxs))
    w('<p class="sortnote"><b>排序规则</b>：先按作曲家，顺序与上面「目录」的分类一致'
      '（贝多芬 → 莫扎特/舒伯特 → 肖斯塔科维奇 → 施特劳斯家族 → 柴可夫斯基/拉赫玛尼诺夫/德沃夏克 → 其他古典 → 中国 → 俄苏 → 流行）；'
      '同一位作曲家内按体裁（交响曲 → 协奏曲 → 奏鸣曲 → 组曲/芭蕾 → 序曲 → 交响诗 → 弥撒 → 变奏/幻想 → 歌曲 → 四重奏 → 小夜曲/嬉游曲 → 舞曲）；'
      '体裁相同再按作品编号从小到大（第几号 → Op. → K.）。</p>')
    w('<div class="idxlist">')
    for comp in sorted(by_comp, key=lambda c: (composer_rank(c), c)):
        hay = ' '.join([comp] + [wk.get('title') or '' for wk, _x in by_comp[comp]])
        w(f'<div class="idxgrp" data-search="{esc(hay)}"><h4>{esc(comp)}</h4><table>')
        for wk, idxs in sorted(by_comp[comp], key=lambda x: work_sort_key(x[0])):
            links = []
            seen_i = set()
            for i in idxs:
                if i in seen_i:
                    continue
                seen_i.add(i)
                al = albums[i]
                kn = kn_albums.get(al['name'], {})
                links.append(f'<a href="#{aid(al["name"])}" title="{esc(display_name(al["name"]))}">{i + 1:02d}·{esc(short_perf(kn, al["name"]))}</a>')
            body = '、'.join(links[:6]) + (f' 等 {len(links)} 版' if len(links) > 6 else '')
            w(f'<tr id="w-{esc(wk["_id"])}"><td style="width:40%">{esc(wk.get("title"))}</td>'
              f'<td><b>{len(idxs)}</b> 版：{body}</td></tr>')
        w('</table></div>')
    w('</div>')

    # 正文
    w('<h2 id="body">唱片详解</h2>')
    render_errors = 0
    for i, al in enumerate(albums):
        try:
            w(render_album(i + 1, al, kn_albums.get(al['name']), works, album_order, work_index))
        except Exception as e:
            render_errors += 1
            w(f'<section class="album"><h2 class="title">{esc(al["name"])}</h2>'
              f'<p class="warn">渲染出错：{esc(type(e).__name__ + ": " + str(e))}</p></section>')

    # 附录
    w('<h2 id="appendix">附录</h2>')
    # 散落文件（只在本机版出现）
    if not PUBLIC:
        w('<h3>散落文件（不在任何专辑目录里）</h3><div class="idxlist"><table>'
          '<tr><th style="width:46%">文件</th><th>说明</th></tr>')
        for x in inv['loose']:
            knx = loose_kn.get(x['name'], {})
            note = knx.get('note') or '（尚未写说明）'
            tg = x.get('tags') or {}
            w(f'<tr><td><code>{esc(x["name"])}</code><div style="color:#6b635b;font-size:12px">'
              f'{fmt_size(x["size"])}' + (f' · {esc(tg.get("spec",""))}' if tg.get('spec') else '') + '</div></td>'
              f'<td>{esc(note)}</td></tr>')
        w('</table></div>')

    # 待整理
    junk = [(a['name'], a['junk']) for a in albums if a['junk']]
    if junk and not PUBLIC:
        w('<h3>可清理的残留文件</h3>')
        w('<p style="font-size:13.5px">以下是历史留下的备份/中间产物（<code>.cue.bak</code>、<code>.bak-scan</code> 等），不影响播放，占地方。确认无用就可以删。</p>')
        w('<div class="idxlist"><table><tr><th style="width:46%">专辑</th><th>文件</th></tr>')
        for n, js in junk[:40]:
            w(f'<tr><td>{esc(n)}</td><td>' + '、'.join(f'<code>{esc(x["name"])}</code>' for x in js[:8])
              + (f' 等 {len(js)} 个' if len(js) > 8 else '') + '</td></tr>')
        w('</table></div>')

    # 未建条目
    missing = [a['name'] for a in albums if a['name'] not in kn_albums]
    if missing:
        w('<h3>还没写讲解的专辑</h3><p style="font-size:13.5px">' + '、'.join(esc(m) for m in missing) + '</p>')

    # 更新记录
    w('<h2 id="changelog">更新记录</h2>')
    if PUBLIC:
        w('<p style="font-size:13.5px;color:#6b635b">下面是最新的几次更新。</p>')
    else:
        w('<p style="font-size:13.5px;color:#6b635b">这份 HTML 每次重建都会升版本号，旧版整份留在 '
          '<code>archive\\\\</code> 里。下面的表格是最近几次的变更。</p>')
    hist = state.get('history', [])[:]
    if not args.dev:
        hist = [{'version': ver, 'ts': now_s, 'note': args.note or '自动重建',
                 'added': added, 'changed': changed, 'removed': removed}] + hist
    w('<div class="idxlist"><table><tr><th style="width:8%">版本</th><th style="width:20%">生成时间</th>'
      '<th style="width:26%">说明</th><th>变化</th></tr>')
    for hrec in hist[:14]:
        ch = []
        if hrec.get('added'):
            ch.append('新增 ' + '、'.join(x[:22] for x in hrec['added'][:4]))
        if hrec.get('changed'):
            ch.append('更新 ' + '、'.join(x[:22] for x in hrec['changed'][:4]))
        if hrec.get('removed'):
            ch.append('移出 ' + '、'.join(x[:22] for x in hrec['removed'][:4]))
        w(f'<tr><td>v{hrec.get("version")}</td><td>{esc(hrec.get("ts"))}</td>'
          f'<td>{esc(hrec.get("note"))}</td><td>{esc("；".join(ch) or "—")}</td></tr>')
    w('</table></div>')

    # 术语表
    w('<h3>速查：规格与厂牌缩写</h3>')
    terms = [('16-44 / 24-96 / 24-192', '位深与采样率，16bit/44.1kHz 是 CD 标准，24/96 与 24/192 是高解析'),
             ('SACD / DSD', '超级音频 CD；DSD 的采样率是 44.1kHz 的 64 倍（DSD64）、128 倍（DSD128）…'),
             ('FLAC / APE / WAV / WV', '无损压缩、无损压缩、未压缩、无损压缩（WavPack）'),
             ('ISO / BDMV', '整盘镜像；BDMV 是蓝光音频/影碟目录结构，通常一个 m2ts 里装着整场音频'),
             ('DG / Decca / Philips', '德意志留声机 / 迪卡 / 飞利浦（后二者现同属环球）'),
             ('Melodiya / Tahra / Marco Polo', '苏联旋律 / 法国历史录音厂牌 / 香港马可勃罗（拿索斯旗下）'),
             ('Op. / K. / D. / WoO', '作品号 / 莫扎特克歇尔编号 / 舒伯特编号 / 贝多芬无编号作品'),
             ('SHM-SACD / Esoteric', '日本环球的高音质 CD 材质 / 日本 Esoteric 的母带重制系列'),
             ('MONO / Stereo', '单声道 / 立体声；二战前后的录音多为单声道')]
    w('<div class="idxlist"><table><tr><th style="width:30%">写法</th><th>意思</th></tr>')
    for a, b in terms:
        w(f'<tr><td><code>{esc(a)}</code></td><td>{esc(b)}</td></tr>')
    w('</table></div>')

    # 页脚
    foot = (f'版本 v{ver}　·　{now_s}　·　专辑 {len(albums)}　·　音轨 {tot_tracks}　·　'
            f'作品条目 {len(works)}（乐章 {mv_total}）')
    if PUBLIC:
        w(f'<footer>{foot}<br>文字内容为本目录自撰，不含唱片封面等版权素材。</footer>')
    else:
        w(f'<footer>本文件由 <code>tools\\\\scan.py</code>（扫描）+ <code>build.py</code>（渲染）'
          f'自动生成；内容知识存在 <code>data\\\\knowledge\\*.json</code>，改 JSON 后重跑 build.py 即可。'
          f'<br>版本 v{ver}　·　{now_s}　·　专辑 {len(albums)}　·　音轨 {tot_tracks}　·　'
          f'作品条目 {len(works)}（乐章 {mv_total}）　·　文字内容为本目录自撰，'
          f'不含唱片封面等版权素材</footer>')
    # 搜索索引（推荐框用）
    idx = {'w': [], 'c': [], 'a': []}
    for wid, idxs in work_index.items():
        wk = works_map[wid]
        idx['w'].append({'a': 'w-' + wid, 't': wk.get('title') or wid,
                         'c': (wk.get('composer') or '').split(' ')[0], 'n': len(idxs),
                         'k': ' '.join(wk.get('_aliases') or [])[:400]})
    idx['w'].sort(key=lambda x: x['n'] * -1)
    for key in sorted(cats, key=lambda k: cat_seq.get(k, 99)):
        idx['c'].append({'a': 'cat-' + key, 't': cats[key]['label'],
                         'n': len(cats[key]['items']), 'k': cats[key]['label']})
    album_works = {}
    for wid, idxs in work_index.items():
        for i in idxs:
            album_works.setdefault(i, []).append(works_map[wid].get('title') or wid)
    for i, al in enumerate(albums):
        kn = kn_albums.get(al['name']) or {}
        meta = ' · '.join(filter(None, [(kn.get('performer') or '')[:34],
                                        kn.get('recorded') or '', kn.get('label') or '']))
        idx['a'].append({'a': aid(al['name']), 't': f'{i + 1:02d} · {disp(al["name"], kn)}',
                         'm': meta or ('%d 轨' % al['stats']['n_tracks']),
                         'k': ' '.join(filter(None, [al['name'], kn.get('composer'),
                                                     kn.get('performer'), kn.get('label'),
                                                     kn.get('edition'), kn.get('recorded'),
                                                     kn.get('released'),
                                                     ' '.join(kn.get('tags') or []),
                                                     ' '.join(album_works.get(i, []))]))[:420]})
    w('<script>var __IDX=' + json.dumps(idx, ensure_ascii=False) + ';</script>')
    w(f'<script>{JS}</script></div></body></html>')

    doc = '\n'.join(H)
    os.makedirs(CDIR, exist_ok=True)
    target = DEV_HTML if args.dev else OUT_HTML
    if not args.dev:
        # 归档旧版
        if os.path.exists(OUT_HTML):
            os.makedirs(ARCHIVE, exist_ok=True)
            prev = state.get('version', 0)
            stamp = time.strftime('%Y%m%d_%H%M', now)
            dst = os.path.join(ARCHIVE, f'音乐库目录_v{prev}_{stamp}.html')
            try:
                shutil.copy2(OUT_HTML, dst)
            except Exception as e:
                print('  归档失败:', e)
    open(target, 'w', encoding='utf-8').write(doc)

    if not args.dev:
        state['version'] = ver
        state['albums'] = new_fp
        state.setdefault('history', []).insert(0, {
            'version': ver, 'ts': now_s, 'note': args.note or '自动重建',
            'added': added, 'changed': changed, 'removed': removed,
            'tracks': tot_tracks, 'albums': len(albums)})
        state['history'] = state['history'][:60]
        json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        # 人读日志
        lines = []
        if not os.path.exists(LOG):
            lines.append('# 音乐库目录 · 更新日志\n')
            lines.append('每重建一次升一个版本，旧版整份归档在 `archive\\`。\n')
        lines.append(f'\n## v{ver} · {now_s}\n\n{args.note or "自动重建"}\n')
        lines.append(f'- 专辑 {len(albums)} 张 / 音轨 {tot_tracks} 条 / 作品条目 {len(works)} 部')
        if added:
            lines.append('- 新增：' + '、'.join(added[:10]) + (f' 等 {len(added)} 张' if len(added) > 10 else ''))
        if changed:
            lines.append('- 内容变动：' + '、'.join(changed[:10]) + (f' 等 {len(changed)} 张' if len(changed) > 10 else ''))
        if removed:
            lines.append('- 移出：' + '、'.join(removed[:10]) + (f' 等 {len(removed)} 张' if len(removed) > 10 else ''))
        lines.append('')
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines))

    print(f'OK v{ver} -> {target}')
    print(f'  albums={len(albums)} tracks={tot_tracks} works={len(works)} movements={mv_total}')
    print(f'  有专辑讲解 {have_notes}/{len(albums)}；曲目命中作品 {matched_tracks}/{tot_tracks}')
    if render_errors:
        print(f'  !!! {render_errors} 张专辑渲染失败')
    if added:
        print(f'  added {len(added)}: ' + ', '.join(added[:6]))
    if changed:
        print(f'  changed {len(changed)}: ' + ', '.join(changed[:6]))
    if removed:
        print(f'  removed {len(removed)}: ' + ', '.join(removed[:6]))
    if conflicts:
        print(f'  知识库重复条目 {len(conflicts)} 条（已跳过后来的）')


if __name__ == '__main__':
    main()

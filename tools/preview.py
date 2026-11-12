# -*- coding: utf-8 -*-
"""把某一节单据抽出来做成单独的预览页，方便截图检查排版"""
import io
import os
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, 'docs')

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
DEV = os.path.join(DOCS, '_dev.html')
src = DEV if os.path.exists(DEV) else os.path.join(DOCS, 'index.html')
dst = os.path.join(DOCS, '_preview.html')
kw = sys.argv[1] if len(sys.argv) > 1 else ''
s = io.open(src, encoding='utf-8').read()
css = re.search(r'<style>(.*?)</style>', s, re.S).group(1)
i = s.find('<section class="album" id=')
sec = None
while i >= 0:
    j = s.find('</section>', i) + 10
    seg = s[i:j]
    if kw.lower() in seg.lower()[:800]:
        sec = seg
        break
    i = s.find('<section class="album" id=', j)
if sec is None:
    print('not found')
    sys.exit(1)
html = ('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
        f'<style>{css}</style></head><body><div class="wrap">{sec}</div></body></html>')
io.open(dst, 'w', encoding='utf-8').write(html)
print('WROTE', dst, len(html))

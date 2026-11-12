# -*- coding: utf-8 -*-
"""抽出一个专辑 section 的源码，便于检查 HTML 结构"""
import io
import os
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, 'docs')

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
html_path = os.path.join(DOCS, 'index.html')
kw = sys.argv[1] if len(sys.argv) > 1 else 'Böhm'
n = int(sys.argv[2]) if len(sys.argv) > 2 else 9000
s = io.open(html_path, encoding='utf-8').read()
i = s.find('<section class="album" id=')
idx = 0
while True:
    j = s.find('</section>', i)
    seg = s[i:j + 10]
    idx += 1
    if kw.lower() in seg.lower()[:600]:
        out = seg[:n]
        io.open(os.path.join(REPO, '_snippet.html'), 'w', encoding='utf-8').write(out)
        print('WROTE snippet, section', idx, 'len', len(seg))
        break
    i = s.find('<section class="album" id=', j)
    if i < 0:
        print('not found')
        break

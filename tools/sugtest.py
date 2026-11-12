# -*- coding: utf-8 -*-
"""截图验证搜索推荐框：注入输入后直接截顶部"""
import io
import os
import subprocess
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(REPO, 'docs')

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = REPO
SRC = os.path.join(DOCS, '_dev.html')
EDGE = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'

html = io.open(SRC, encoding='utf-8').read()
for i, q in enumerate(sys.argv[1:] or ['贝九']):
    inject = ('<script>window.addEventListener("load",function(){'
              'var inp=document.getElementById("q");'
              'inp.value=%r;' % q
              + 'inp.dispatchEvent(new Event("input"));inp.focus();});</script>')
    out_html = os.path.join(BASE, '_tmp_sug%d.html' % i)
    io.open(out_html, 'w', encoding='utf-8').write(html.replace('</body>', inject + '</body>'))
    png = os.path.join(BASE, '_tmp_sug%d.png' % i)
    subprocess.run([EDGE, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--virtual-time-budget=4000', '--window-size=1120,760',
                    f'--screenshot={png}', 'file:///' + out_html.replace('\\', '/')],
                   capture_output=True, timeout=120)
    print(q, '->', png, os.path.exists(png))

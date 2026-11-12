# -*- coding: utf-8 -*-
"""搜索自测 v2：过滤后把结果写成纯文本页面，直接看命中清单"""
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

queries = sys.argv[1:] or ['贝九']
html = io.open(SRC, encoding='utf-8').read()

for i, q in enumerate(queries):
    inject = '''<script>window.addEventListener("load",function(){
      var inp=document.getElementById("q");
      inp.value=%s; inp.dispatchEvent(new Event("input"));
      var out=[];
      document.querySelectorAll("section.album").forEach(function(s){
        if(!s.classList.contains("hidden")){
          out.push(s.querySelector("h2.title").textContent.replace(/\\s+/g," ").trim().slice(0,70));
        }
      });
      var toc=[];
      document.querySelectorAll(".toc li").forEach(function(li){
        if(!li.classList.contains("hidden")) toc.push(li.textContent.replace(/\\s+/g," ").trim().slice(0,50));
      });
      document.body.innerHTML="<pre style='font:15px/1.7 Consolas,monospace;padding:20px;white-space:pre-wrap'>"
        +"查询: %s\\n命中专辑: "+out.length+"\\n\\n"+out.join("\\n")+"\\n\\n-- 目录里剩下的条目 --\\n"+toc.join("\\n")+"</pre>";
    });</script>''' % ('"%s"' % q, q)
    out_html = os.path.join(BASE, '_tmp_qq%d.html' % i)
    io.open(out_html, 'w', encoding='utf-8').write(html.replace('</body>', inject + '</body>'))
    png = os.path.join(BASE, '_tmp_qq%d.png' % i)
    subprocess.run([EDGE, '--headless=new', '--disable-gpu', '--hide-scrollbars',
                    '--virtual-time-budget=4000', '--window-size=1100,760',
                    f'--screenshot={png}', 'file:///' + out_html.replace('\\', '/')],
                   capture_output=True, timeout=120)
    print(q, '->', png, os.path.exists(png))

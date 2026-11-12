# -*- coding: utf-8 -*-
"""发布前自检：页面上不许出现本机路径、文件名、体积、残留文件清单。
用法：python check_public.py
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(REPO, 'docs', 'index.html')

# 页面上不该出现的（本机信息）
FORBIDDEN = [
    (r'[A-Za-z]:\\\\', '盘符路径'),
    (r'\\\\音乐\\\\|\\\\_目录', '本机目录名'),
    (r'库根', '库根字样'),
    (r'文件清单', '文件清单'),
    (r'磁盘占用', '磁盘占用'),
    (r'散落文件', '散落文件'),
    (r'可清理', '可清理残留'),
    (r'占用空间', '占用空间'),
    (r'文件夹', '文件夹'),
    (r'文件名', '文件名'),
    (r'抓轨', '抓轨'),
    (r'整轨', '整轨'),
    (r'\bEAC\b', 'EAC'),
    (r'\.(iso|ape|flac|dsf|wav|m4a|wv|mp3)\b', '音频文件名'),
    (r'\.(cue|bak|lrc|log|accurip)\b', '抓轨附属文件'),
    (r'<img', '图片引用'),
]


def visible_text(html):
    body = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', body)
    return re.sub(r'\s+', ' ', text)


def main():
    if not os.path.exists(HTML):
        print('没有 docs/index.html，先跑 build.py')
        return 1
    html = io.open(HTML, encoding='utf-8').read()
    text = visible_text(html)
    bad = 0
    print(f'检查 {HTML}（{len(html.encode()) / 1048576:.2f} MB，可见文本 {len(text)} 字）')
    for pat, name in FORBIDDEN:
        n = len(re.findall(pat, text))
        if n:
            bad += n
            print(f'  ✗ {name}: {n} 处')
            for m in list(re.finditer(pat, text))[:3]:
                print('      …' + text[max(0, m.start() - 40):m.start() + 40] + '…')
    imgs = []
    for dp, _dn, fns in os.walk(REPO):
        if os.sep + '.git' in dp or os.sep + 'assets' in dp:
            continue
        for fn in fns:
            if os.path.splitext(fn)[1].lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tif'):
                imgs.append(os.path.join(dp, fn))
    if imgs:
        bad += len(imgs)
        print(f'  ✗ 仓库里有 {len(imgs)} 个图片文件（应无）：')
        for p in imgs[:5]:
            print('      ' + os.path.relpath(p, REPO))
    print('结果：' + ('通过，页面不含本机信息' if bad == 0 else f'还有 {bad} 处要处理'))
    return 0 if bad == 0 else 2


if __name__ == '__main__':
    sys.exit(main())

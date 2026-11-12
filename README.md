# 音乐库目录

一套本地古典音乐收藏的**唱片目录**：102 张唱片 / 3363 条音轨 / 183 部作品。每张唱片一页，写清这一版是什么版本、好在哪、和库内其它版本差在哪，以及每部作品的背景与**逐乐章 / 逐曲说明**。

线上站点：GitHub Pages，发布目录是 **`docs/`**（入口 `docs/index.html`）。

> **这个仓库不含唱片封面。** 封面是唱片公司的版权素材，页面里用一条按作曲家取色的排版书脊占位。
> 想在本机看真封面，`python build.py --covers`（生成在 `docs/assets/`，别提交）。

## 长什么样

- **目录**：按作曲家分类，每张一条，带一句话定位；
- **作品索引**：同一部作品在库里有哪些版本，按作曲家 → 体裁 → 作品号排序，点进去看逐版详解；
- **单张唱片**：元信息 → 一句话定位 → 版本详解（录音与阵容 / 版本与转制 / 听感与特色 / 收藏与使用）→ 同源与同曲对照 → 曲目与逐曲讲解 → 文件清单；
- **搜索**：输入时弹推荐清单，分「作曲家 / 作品 / 唱片」三类，回车跳转；`贝九`、`命运`、`皇帝`、`K.334`、`symphony 9` 都认；
- **SACD / 蓝光镜像**：能读碟内元数据的读元数据，读不到的按镜像名推断，实在不行人工补录，所以 ISO 里的曲目也能在索引里找到。

## 仓库结构

```
docs/                    GitHub Pages 发布目录
  index.html             目录主页（单文件，约 3 MB，无任何图片引用）
  .nojekyll              关掉 Jekyll，避免下划线文件被吃掉
data/
  inventory.json         扫描结果：专辑 / 碟 / 轨 / 时长 / 采样规格 / CUE / 镜像
  knowledge/*.json       讲解内容（按作曲家分组，人写或模型写）
  state.json             版本号与每张专辑的指纹（增量判断用）
tools/
  scan.py                扫描音乐库 → inventory.json（只读文件头）
  build.py               合并数据 + 知识库 → docs/index.html（自动升版本、归档、写日志）
  digest.py check.py audit.py coverage.py preview.py searchtest.py sugtest.py   体检/调试脚本
更新日志.md               每版的变更记录
使用说明.md               给使用者看的详细说明（怎么更新、怎么加讲解、怎么部署）
```

`archive/`（旧版 HTML）只在本机存在，已写进 `.gitignore`：每次发布本身是一次 commit，git 历史就是归档。

## 本地生成

需要 Python 3，以及 `mutagen`（读标签）；只有加 `--covers` 时才需要 `pillow`：

```bash
python -m pip install mutagen pillow

cd tools
python scan.py                                  # 库里加了文件就重扫
python build.py --note "补了 XX 的贝九"          # 出 docs/index.html，升版本，写日志
python build.py --covers                        # 额外导出封面到 docs/assets（本机看，别提交）
```

开发时用 `python build.py --dev`：写到 `docs/_dev.html`，不升版本、不归档、不写日志。

工具里的路径是**相对仓库根**推出来的（`tools/` 的上一级），所以整个目录搬到哪儿都能跑；只需要设 `MUSIC_ROOT` 环境变量（或改 `build.py` 顶部的默认值）指向你自己的音乐库。

## 部署到 GitHub Pages

1. 推到 GitHub（`main` 分支）；
2. 仓库 **Settings → Pages → Build and deployment**：Source 选 **Deploy from a branch**，分支 `main`、目录 **`/docs`**，保存；
3. 等一两分钟，地址是 `https://<用户名>.github.io/<仓库名>/`。

页面里的资源全是相对路径，放在子路径下也不会断。`docs/.nojekyll` 由 `build.py` 自动生成，别删。

## 版权

- **文字**：本目录自撰，可以随意引用。
- **封面**：不收录。`--covers` 只用于本机预览，生成的 `docs/assets/` 已在 `.gitignore` 里，请勿提交或发布。
- **元数据**：曲名、作曲家、编号、时长、唱片编号属于事实信息，不含受保护的表达。

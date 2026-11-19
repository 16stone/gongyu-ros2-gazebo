# 课程报告 v11

- 交付件：`潘道熙25361130课程设计报告题目二_v11.docx`（可编辑）与同名 `.pdf`（由同一 DOCX 导出），校验和见 `SHA256SUMS`。
- 同源编辑入口：`body.md`。正文、表格、图注都在这一份 Markdown 里，改完重跑构建即可，DOCX 与 PDF 不会分叉。
- `body_v9.md` 是 v9 原稿，保留用于对照，不参与构建。

## 构建

```bash
cd report_v11
/home/liujingzhi/miniconda3/bin/python src/draw_webots_figs.py   # 重绘图 16 / 图 17（数据取自 f-webots-full-01）
/home/liujingzhi/miniconda3/bin/python src/build_v11.py           # 两遍：先出 PDF 取页码，再回填目录
```

`src/patch_v11.py` 记录本次相对 v9 正文的增量（摘要、1.5 节、6.12–6.14、第 7 章、参考文献 [13]），
用于从 `body_v9.md` 复现出 `body.md`；日常修改直接改 `body.md`。

## 约定

- 页数、图数、表数由 `build_v11.py` 在构建时打印，不手填。
- 图内文字用 `Noto Sans CJK` 绘制；`DroidSansFallbackFull.ttf` 只有 CJK 字形，拉丁字母与数字会变成方框。
- 目录页码来自第一遍 PDF 的正文首行定位，`摘要` 之前的目录页不参与匹配。

# v10 课程报告（同源交付）

- `潘道熙25361130课程设计报告题目二_v10.docx`：可编辑正文，7 页/4210 个中文字符（不含图表标题计数差异）。
- `潘道熙25361130课程设计报告题目二_v10.pdf`：由同一 DOCX 经 LibreOffice 7.3 导出，内容与图表同源。
- `figures/`：四张由证据数据绘制的图表；`src/draw_figs.py` 用 Pillow 生成（amax 上 matplotlib 字形渲染不可用）。
- 生成命令（amax）：
  `/home/liujingzhi/miniconda3/bin/python report_v10/src/draw_figs.py`
  `/home/liujingzhi/miniconda3/bin/python report_v10/src/build_report.py`
  `HOME=/tmp/lohome_v10 soffice --headless --convert-to pdf --outdir report_v10 report_v10/潘道熙25361130课程设计报告题目二_v10.docx`
- 数据入口：`evidence/webots/<run-id>/`、`docs/demo/webots_replay_data.json`、`docs/acceptance_status.md`。
- 注意：报告正文明确写出正式整机使用运动学裁判后端、真实电机整机未闭合；不要删改该边界说明。

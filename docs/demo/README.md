# Webots 整机同源回放

| 文件 | 内容 |
| --- | --- |
| `webots_replay.html` | 自包含深色科技风演示页，内嵌 8 实体轨迹、153 条同源事件与关键指标；支持播放/暂停、四档速度、时间轴拖拽、四章节跳转（开始 / 协同报告 / 共享通道 / 交付） |
| `webots_full_run.mp4` | 44 s、1200×1080、25 fps 的同源视频，收尾 3 s 定格显示 14/14 与 0 违例 |
| `webots_replay_data.json` | 两者的共同数据源 |
| `course_final_replay.mp4` | 53 s，交稿版配套整机回放。与 `webots_full_run.mp4` 是两次不同生成；交稿回合与历史回合的数字按各自回执读取，不混用 |

上表前两项的数据来源：amax Webots R2025a CPU 历史主回合 `f-webots-full-01`，原始运行目录 `~/pandaoxi/gongyu-webots-runs/reverify-full2/`，回合摘要在 `evidence/webots/f-webots-full-01/`。

- 位置取自裁判保存的 `truth_trajectories`（500 ms 采样、每实体 81 点），是**独立真值**而不是控制器自报；早期版本用控制器 `odom`，导致两架 UAV 因为没有里程计而被画在原点，已修正。
- 事件取自同一回合的 `bus/events.jsonl`（153 条），计数取自 `metrics.json`。
- 轨迹在采样点之间做线性插值以保持视觉连续；判据数字一律取自 `metrics.json` 与事件流，不做任何手工补帧或示意动画。
- 重新生成：`python3 docs/tools/make_replay_data.py` 后接 `python3 docs/tools/render_replay_video.py`（视频）或 `python3 /tmp/reinject_html.py` 式的数据注入（页面）。

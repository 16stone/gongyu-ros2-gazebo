# 共域 · 空地无人系统协同（Webots v10 交付）

《无人系统导论》课程设计题目二《一条通道上的两支队伍：空地无人系统协同靶场的设计与复盘》。

6 辆差速地面车与 2 架无人机在两个作业区之间执行侦察与运输任务，共用一条容量为一的窄通道。任务层用带有效期的观测、动态改派与通道预约协调多台实体，岗位分配把"抽调平台去帮忙"的机会成本纳入选择。本版把整机从 Gazebo 迁移到 **Webots R2025a**，在 CPU 上完成八实体实跑，并由**独立裁判**判定真值，不再采信控制器自报。

## 主回合

`evidence/webots/f-webots-full-01`：八实体（6 UGV + 2 UAV）、冻结场景 `web_medium`、提前释放机制开启。

**14/14 项任务按期 · 0 条通道违例 · 5 次进入 / 5 次释放 · 9 份报告接受 · 0 过期。**

[指标](evidence/webots/f-webots-full-01/metrics.json) · [裁判事件](evidence/webots/f-webots-full-01/events.jsonl) · [关闭回执](evidence/webots/f-webots-full-01/shutdown.json) · [场景哈希](evidence/webots/f-webots-full-01/scene.sha256)

## 交付入口

| 路径 | 内容 |
| --- | --- |
| [report_v11](report_v11) | 课程报告 DOCX / PDF（55 页、29315 中文字符、17 图 40 表）与同源正文 `body.md`、构建脚本、SHA256SUMS |
| [docs/evidence_index.md](docs/evidence_index.md) | 实验索引，33 个回合，由证据目录自动生成 |
| [docs/demo/webots_full_run.mp4](docs/demo/webots_full_run.mp4) | 主回合同源视频（44 s / 1200×1080 / 25 fps），画面取自裁判真值与同一批事件 |
| [docs/demo/webots_replay.html](docs/demo/webots_replay.html) | 可交互回放页，时间轴、四档速度、四章节跳转 |
| [docs/course_alignment](docs/course_alignment) | 课件原理—设计问题—方案—证据对照，含题号与 slide 校核 |
| [docs/webots/PHYSICAL_LAYER.md](docs/webots/PHYSICAL_LAYER.md) | 真实电机分支的完整诊断记录与未闭合边界 |
| [docs/acceptance_status.md](docs/acceptance_status.md) | 验收状态、回归验证与仍然开放的项 |
| [webots](webots) | 世界生成器、控制器、独立裁判、运行器、冻结场景卡 |
| [evidence/webots](evidence/webots) | 33 个回合的指标、事件、关闭回执与场景哈希 |

## 关键对照

| 对照 | 回合 | 结果 |
| --- | --- | --- |
| 通道机制开 / 关 | `e-mech-release` / `e-mech-phase111` | 0 违例 / **2 违例**（负结果保留） |
| 报告按时 / 过期 | `d-report-ontime` / `d-report-expired` | 9 接受 0 过期 / 0 接受 9 过期 |
| 过期后改派 | `d-adapt` | 9 次改派，触发与候选拒绝理由逐条可查 |
| 机会成本 | `d-cost-high` | 判据翻转，14/14 不延期 |
| 预登记留出场景 | `f-holdout-v1` | 14/14、0 违例 |
| 定位来源 | `b-loc-gps-*` | 对独立真值 RMSE **0.074 m** |
| 双扫描覆盖 | `b-scan-lowobs-*` / `b-scan-open-*` | 低位命中 **2** / **0**（首次回波 0.161 m） |

## 复现

```bash
# 主回合（约 2 分钟，CPU，无渲染）
GONGYU_MECH=release GONGYU_END_MS=200000 GONGYU_WALL_LIMIT=900 \
  bash webots/tools/run_webots.sh web_medium my-run-id

# 真实电机（单车）
GONGYU_PHYS=1 GONGYU_NO_RENDER=1 GONGYU_END_MS=140000 \
  bash webots/tools/run_webots.sh web_b1_clear_phys my-phys-run
```

回执写入 `~/pandaoxi/gongyu-webots-runs/<run-id>/`（`bus/tel_*.jsonl` 逐实体遥测、`bus/events.jsonl` 裁判事件、`result/metrics.json` 判据输出、`shutdown.json` 关闭回执、`environment.txt` 环境与退出码）。需要 Xvfb 与 `LIBGL_ALWAYS_SOFTWARE=1`，运行器已内置。

## 执行器层

真实电机分支已让**单车**跑完整条路线（`p-motor-b1-route`：D→W→E→L→O，通道 2.0574 m 进入、4.9504 m 清空，1/1 按期、0 违例）；**八实体电机整机未闭合**（11/14 与 13/14 两次尝试），根因是通道口航点与占用判据的几何错位，而非控制律。正式验收证据因此仍取运动学后端，两者不相加。详见 [PHYSICAL_LAYER.md](docs/webots/PHYSICAL_LAYER.md)。

## 历史版本

- **v9（Gazebo）**：`fp124-ent-ind-01` 在 phase124-wslgpu 冻结版本上 14/14、0 违例、5 次通道持有与释放，每实体独立进程决策。完整录屏与 v9 报告见 [课程归档发布页](https://github.com/16stone/gongyu-ros2-gazebo/releases/tag/v9-course)。
- `scenes/`、`source/`、`PROJECT.SHA256` 保留 v9 Gazebo 场景与源码，供历史对照与复现。
- Gazebo 在本项目中承担筛选与历史对照；正文中的平台、版本、场景、回合四项均逐表标注，不把两个后端的秒数或完成率相加。

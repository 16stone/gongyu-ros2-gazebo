# Webots 整机同源回放

- `webots_replay.html`：自包含深色科技风演示，内嵌 `f-webots-full-01` 的 8 实体采样轨迹（原始遥测每 4 条取 1 条，2 s 采样）、153 条同源事件、四项关键指标。
- 数据来源：amax Webots R2025a CPU 主回合 `f-webots-full-01`，原始运行目录 `~/pandaoxi/gongyu-webots-runs/f-webots-full-01/`；回合摘要在 `evidence/webots/f-webots-full-01/`。
- 页面提供播放/暂停、四档速度、时间轴拖拽与四个章节跳转（开始 / 协同报告 / 共享通道 / 交付）。
- 轨迹为真实遥测抽样后的线性插值显示，不是重新仿真的结果；节点间插值仅用于视觉连续，判据数字一律取自 `metrics.json` 与事件流。

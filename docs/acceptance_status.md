# 验收状态（2026-11-19，amax 执行）

## 已闭合
- Webots R2025a / amax CPU / Xvfb 软件渲染与 `--no-rendering` 两种模式可用；世界、控制器、场景 SHA256、关闭回执齐备。
- 阶段 D/E/F 8 个回合：报告按时 / 过期 / 动态改派 / 机会成本、机制全关与提前释放、预登记留出、6 UGV + 2 UAV 整机，均 14/14 按期、webots_exit=0、COMPLETE；`e-mech-phase111` 保留 2 条通道重叠违例作为负结果对照。
- 阶段 B/C 18 个回合：双扫描、定位、UAV 反馈三种对照各 3 次独立重启；低位扫描命中 2 对 0，GPS 定位 RMSE 0.074 m 对轮式 2.764 m，UAV 反馈标签可追。

## 边界与未闭合
- 正式整机回合采用独立裁判运动学真值；`GONGYU_PHYS=1` 的真实电机模式只完成单机过口/到位与根因诊断，8 实体整机停在 L→O 路段，未形成完整 14/14，见 `docs/webots/BACKEND_NOTES.md`。
- `web_b1_gate`、`web_b1_unmapped`、`web_long`、`web_cost` 等矩阵场景尚未生成专门世界；B-plan（Dijkstra/A*）与出口泊位检查仍以 v9 Gazebo 证据支撑，不与 Webots 秒数混算。
- C-ref / C-auto 的开关仅改变反馈来源标签，不能据此宣称 UAV 自主飞行效能；报告中按“已实现层级”写明。
- 三次重启因模型确定性结果一致，登记为独立重启而非统计重复。

## 复现入口
`webots/tools/run_webots.sh <scene> <run-id>`；默认运动学后端，`GONGYU_PHYS=1` 切真实电机实验，
`GONGYU_NO_RENDER=1` 关闭主视图渲染。回执写入 `~/pandaoxi/gongyu-webots-runs/<run-id>/`，摘要提交到 `evidence/webots/<run-id>/`。

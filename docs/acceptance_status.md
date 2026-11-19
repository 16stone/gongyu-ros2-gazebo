# 验收状态（2026-11-19，amax 执行）

## 已闭合
- Webots R2025a / amax CPU / Xvfb 软件渲染与 `--no-rendering` 两种模式可用；世界、控制器、场景 SHA256、关闭回执齐备。
- 阶段 D/E/F 8 个回合：报告按时 / 过期 / 动态改派 / 机会成本、机制全关与提前释放、预登记留出、6 UGV + 2 UAV 整机，均 14/14 按期、webots_exit=0、COMPLETE；`e-mech-phase111` 保留 2 条通道重叠违例作为负结果对照。
- 阶段 B/C 18 个回合：双扫描、定位、UAV 反馈三种对照各 3 次独立重启；低位扫描命中 2 对 0（首次回波 0.161 m、可用预警约 1.0 s，逐回合见 `evidence/webots/b-scan-*/scan_stats.json`），GPS 闭环对独立真值 RMSE 0.074 m，UAV 反馈标签可追。
- **更正**：`b-loc-odom-*` 的 2.764 m 不能当作里程计精度。运动学后端电机被置零、编码器不转动，`wheel_odom` 实际是冻结值，该数字只说明「没有里程计读数时离真值多远」。有效对照要在真实电机后端重做，在此之前报告中不引用它作为里程计结论。

## 边界与未闭合
- 正式整机回合采用独立裁判运动学真值。`GONGYU_PHYS=1` 的真实电机分支已定位并修正四个缺陷：偏航符号（器件约定 + 轮侧对应两处叠加）、±π 处航向锁存、机体碰撞盒离地 1 cm、到点判据与通道净空互相卡死；低位雷达与低矮障碍同高这条已定位，仅在物理变体中降到 0.12 m。
  `phys-spin-02` 推翻了早期「四轮滑移转向无法原地搓转」的判断（v=0 给 +0.8 rad/s，15.87 s 累计 12.03 rad、漂移 0.0 m）。
  修好后单车可连过 D/W/E 并在 x=4.9519 m 清空通道（`clear-pass-03`），但走廊口 180° 调头仍被墙端夹住，需倒车机动；八实体整机未闭合。逐条根因与最小复现见 `docs/webots/PHYSICAL_LAYER.md`。
- 低矮障碍场景在物理上不可通行：障碍 `y` 跨度 0.8、中心 0.15，把 1.2 m 通道压到只剩 0.35 m 空隙，而车体宽 0.34 m。属场景移植缺陷，待改为部分遮挡后重跑，不影响运动学后端的双扫描判决。
- `web_b1_gate`、`web_b1_unmapped`、`web_long`、`web_cost` 等矩阵场景尚未生成专门世界；B-plan（Dijkstra/A*）与出口泊位检查仍以 v9 Gazebo 证据支撑，不与 Webots 秒数混算。
- C-ref / C-auto 的开关仅改变反馈来源标签，不能据此宣称 UAV 自主飞行效能；报告中按“已实现层级”写明。
- 三次重启因模型确定性结果一致，登记为独立重启而非统计重复。

## 复现入口
`webots/tools/run_webots.sh <scene> <run-id>`；默认运动学后端，`GONGYU_PHYS=1` 切真实电机实验，
`GONGYU_NO_RENDER=1` 关闭主视图渲染。回执写入 `~/pandaoxi/gongyu-webots-runs/<run-id>/`，摘要提交到 `evidence/webots/<run-id>/`。

## 干净目录复核（2026-11-19）

- 从提交 `f5c6e50` 全新检出到 `~/pandaoxi/gongyu_v10_verify_clean`：26 个 `evidence/webots/<run-id>` 目录齐备。
- 报告 `SHA256SUMS` 两项均 OK；演示页内嵌 JSON 解析成功（8 实体、153 事件、14/14 指标）。
- 以新运行 ID `verify-repro-01` 从干净检出复跑 `web_b1_route`（关闭渲染），与 `b-loc-gps-01` 的场景、按期数、总数、违例数、通道进入/释放数逐项一致。

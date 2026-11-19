# Webots 实跑后端开发记录（amax CPU / R2025a）

## 环境

> 执行器层（真实电机）的完整结论、判定性测量与未闭合边界见 `docs/webots/PHYSICAL_LAYER.md`；本文件保留后端搭建与早期缺陷记录。
- 唯一执行机 amax，Webots R2025a 解压于 `~/pandaoxi/webots`，无 GPU，用 `xvfb_root` 的 Xvfb :99 + `LIBGL_ALWAYS_SOFTWARE=1` + `LD_LIBRARY_PATH` 含 `$WEBOTS/lib/webots`。
- 运行入口 `webots/tools/run_webots.sh <scene> <run-id>`，新运行 ID、场景 SHA256、原始 bus/events/遥测、metrics、shutdown 关闭回执齐备。
- 每次运行快速模式（fast + --batch），墙钟为仿真时钟的约 1.5–2.5 倍。

## 已定位并修复的关键缺陷（负结果诊断）
1. 世界头缺失 `#VRML_SIM R2025a utf8` → Webots 加载失败卡死。
2. `Supervisor {}` 非法节点 → 改为 `Robot { supervisor TRUE }`。
3. 背景 PROTO 远程依赖不存在 → 改用内建 `Background` + 光源。
4. `Supervisor` 应从 `controller` 导入；`InertialUnit.getRollPitchYaw()`；位姿用 `Node.getPosition()`。
5. **坐标系：该 Webots build 为 Z-up**（translation 第三分量为高度），全部几何与控制器映射按 Z-up 重写。
6. 车轮轴错设为 Z 导致原地空转 → 改绕 Y 滚动 + 轮心高度贴合地面；里程计与真值恢复一致。
7. 出生点落在节点中心/通道边界导致 born-in-channel 违例 → 改用 `physical_berths` 分离泊位；通道判据收紧为 x∈(2.05,4.95)。
8. 低位雷达贴地误判障碍致持续降速 → 抬高至 0.18m 并过滤近地回波；车速对齐场景标称 0.5 m/s。

复验回合：`b1-full-*`（单车 4 站+通道，0 违例）、`full-021733`（八实体 4/4 按期、0 违例、4 报告接受）。

## 当前状态（阶段 B/C/D/E/F 均已按矩阵落证据）
- 独立裁判运动学模型驱动的真值源与到位判据已统一（裁判状态机维护每个实体的目标点、洁净通道门控与
  物理 translation；UGV/UAV 控制器通过 Webots 设备读取传感器，执行端 Velocity 置零以避免双重驱动）。
- 2026-11-19 同版 amax CPU Webots 矩阵 8 个回合均 webots_exit=0、status=COMPLETE、14/14 按期：
  d-report-ontime / d-report-expired / d-adapt / d-cost-high /
  e-mech-phase111（2 条违例，作为全关对照负结果）/ e-mech-release /
  f-holdout-v1（预登记留出）/ f-webots-full-01（6 UGV＋2 UAV 整机）。
- 证据落点：`evidence/webots/<run-id>/`，含 metrics/shutdown/events/ctl_events/environment/scene.sha256/summary。
  原始运行目录：`~/pandaoxi/gongyu-webots-runs/<run-id>/`。
- 阶段 B/C 补跑：18 个回合（b-loc-gps / b-loc-odom / b-scan-open / b-scan-lowobs / c-ref / c-auto，
  每处理 3 个独立重启），全部 webots_exit=0 且关闭回执 COMPLETE，证据在 `evidence/webots/<run-id>/`。
  ``--no-rendering`` 仅关闭主视图渲染，不改变物理与控制器时钟。
  - 定位：GPS 闭环自身估计对独立裁判真值的 RMSE 0.074 m，轮式里程计 2.764 m（600 ms 最近时刻配对）。
  - 双扫描：低矮障碍场景低位扫描命中 2 次，开阔场景 0 次；原始 lidar_low_front 序列在对应回合中可复核。
  - UAV：c-ref / c-auto 的 `feedback_mode` 分别为 reference / sensor，传感位姿对真值 XY RMSE 0.114 m。
    当前裁判运动学后端中该开关只改变反馈来源标签，不改变运动，因此**不作为自主飞行效能证据**。
  - 三次重启的随机种子为 0/1/2，但冻结模型不含随机扰动，结果确定性一致；样本量按“独立重启”登记，
    不宣称统计方差。

## 物理执行层（2026-11-19 追加）

真实电机分支的诊断与修复单独记在 `docs/webots/PHYSICAL_LAYER.md`。结论摘要：

- 停滞的主因不是滑移转向几何，而是 **IMU 偏航符号与控制器航向约定相反**：
  `spin-pure-02` 中 `omega=+0.8 rad/s` 对应 `d(yaw)/dt=-0.758 rad/s`，
  航向环因此成为正反馈。此前「四轮矩形布局无法原地搓转」的判断已被该实验推翻并撤回。
- 另修：`±π` 处航向锁存、机体碰撞盒底边由 0.01 m 抬到 0.05 m、万向球外移到 ±0.19 m。
- 物理变体世界 `*_phys.wbt` 用两驱 + 前后万向球，与控制器 `(v ± ωB/2)` 模型严格一致；
  运动学世界不受影响，`scene.sha256` 与已提交证据保持一致。
- 低位雷达安装在 0.18 m，而低矮障碍顶面也是 0.18 m，首次回波只在 0.161 m 出现，
  可用预警约 1.0 s（见 `evidence/webots/b-scan-*/scan_stats.json`）；
  该场景的障碍还把 1.2 m 通道挤到只剩 0.35 m 空隙（车宽 0.34 m），物理上不可通行。
  这两条都是场景/传感器安装缺陷，不是控制缺陷，已按此登记待改。

### 对既有指标的更正

- `b-loc-odom-*` 上的「轮式里程计 RMSE 2.764 m」**不能**当作里程计精度：
  运动学后端中电机被置零、编码器不转动，`wheel_odom` 实际是冻结值，
  该数字只反映「没有里程计读数时离真值多远」。
  有效对照需在物理后端（真实轮子转动）重做，结果见下节与 `PHYSICAL_LAYER.md`。
- 运动学后端的其余指标（按期数、违例数、报告接受/过期、改派次数、通道进入/释放）
  不受上述问题影响，仍作为任务逻辑证据。

## 视觉设计
科技深色主题：深空背景、发光网格与拓扑边、团队双色（蓝/红）、通道金色高亮、多光源、团队地标柱；世界生成完全参数化于冻结场景卡。


## 真实电机模式（GONGYU_PHYS=1）的诊断与边界

- 代码开关：`GONGYU_PHYS=1` 时 UGV 四轮与 UAV 四桨由控制器 `setVelocity` 实际驱动，裁判只读
  `getPosition()` 真值，不再写 `translation`；默认 0 保持既有可复现运动学后端。
- 负结果链：`phys-smoke-01..03` 定位到**静态地面被误设为动态物理体**（`solid()` 默认 `physics=True`），
  整车自由落体 z=-19…=-1959 m。修复为静态地面后生成 `*_phys.wbt` 世界。
- `phys-smoke-04/05` 定位到转弯时轮式航向积分漂移、电机扭矩过大导致车体倾覆；改用 IMU 航向、
  限制轮速 ±6 rad/s 后，`phys-smoke-06` 单车可驶过入口、到达 W/E 站位并保持直立。
- `phys-full-01`（带渲染）墙钟 15 min 只推进约 29 s 仿真；`--no-rendering` 后单车 60 s 仿真约 11 s 墙钟，
  但 8 实体整机 `phys-full-02` 在 ~29 s 处停于 L→O 路段，未形成完整 14/14 回合并已按负结果停止。
- 结论：**正式整机证据仍使用运动学裁判后端；真实电机模式仅作为已定位并部分修复的实验分支**，
  报告需明确写出这一能力边界，不得把运动学回合成交为“电机驱动整机”。

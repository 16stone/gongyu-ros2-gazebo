# Webots 实跑后端开发记录（amax CPU / R2025a）

## 环境
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

## 当前状态（阶段 D/E/F 已闭合，B/C 待补）
- 独立裁判运动学模型驱动的真值源与到位判据已统一（裁判状态机维护每个实体的目标点、洁净通道门控与
  物理 translation；UGV/UAV 控制器通过 Webots 设备读取传感器，执行端 Velocity 置零以避免双重驱动）。
- 2026-11-19 同版 amax CPU Webots 矩阵 8 个回合均 webots_exit=0、status=COMPLETE、14/14 按期：
  d-report-ontime / d-report-expired / d-adapt / d-cost-high /
  e-mech-phase111（2 条违例，作为全关对照负结果）/ e-mech-release /
  f-holdout-v1（预登记留出）/ f-webots-full-01（6 UGV＋2 UAV 整机）。
- 证据落点：`evidence/webots/<run-id>/`，含 metrics/shutdown/events/ctl_events/environment/scene.sha256/summary。
  原始运行目录：`~/pandaoxi/gongyu-webots-runs/<run-id>/`。
- 阶段 B（双扫描、定位、规划、入口门控）与阶段 C（UAV 自主反馈、观测报告）尚未按预登记矩阵补齐，
  报告证据表相应列继续标注“待补”，不把阶段 D/E/F 的结果跨阶段代替。

## 视觉设计
科技深色主题：深空背景、发光网格与拓扑边、团队双色（蓝/红）、通道金色高亮、多光源、团队地标柱；世界生成完全参数化于冻结场景卡。

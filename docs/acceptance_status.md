# 验收状态（2026-11-19，amax 执行）

## 交稿主版本（2026-11-19 收口，覆盖下文历史口径）

- **正式提交**：`report_course_final/`，45 页 / 23026 汉字 / 45 表 / 16 图，PDF 与 DOCX 同源，`SHA256SUMS` 两项 OK；构建后逐项核验通过，目录 62/62 页码逐条命中，PDF 内无遗留反引号与缺图。
- **主版本**：`evidence/course_final/{normal,delay,holdout}`，Webots R2025a CPU，场景 `web_medium_phys` / `web_holdout_v1_phys`；`physical_actuation=true`、`motion_backend=hybrid`、`kinematic_actors=["B3","R5"]`、`corridor_protocol=footprint_serial_dispatch`。三组均 14/14 按期、5 进 5 清、0 违例、400 s 完整窗口。
- **与下文的关系**：下文「执行器层（真实电机）结论」里的 `p-motor-full-01/02` 是采用旧瞬时占用判据的**诊断分支**（分别完成 11 项与 13 项任务，后者记录 5 次重叠），未闭合、不计入交稿结果；`f-webots-full-01` 是运动学筛选回合，承担历史回放与规则配对。交稿主版本改用整个车体的包络判空与串行放行，结论建立在新回执上，三者数字不相加。
- **报告改动**：删除原附录 C 的完成度自评表；新增 1.4 主版本与证据分层、2.1 姿态符号判定性测量、7.2「现象—定位—修改—复验」修改链；把 3.2 的阈值细节与执行器诊断移入新附录 C；附录 A 的证据路径全部改为本仓库实际目录；构建器补行内代码渲染，移除自评表专用列宽与过时标题特例。

## 已闭合

- Webots R2025a / amax CPU / Xvfb 软件渲染与 `--no-rendering` 两种模式可用；世界、控制器、场景 SHA256、关闭回执齐备。
- 阶段 D/E/F 8 个回合：报告按时 / 过期 / 动态改派 / 机会成本、机制全关与提前释放、预登记留出、6 UGV + 2 UAV 整机，均 14/14 按期、`webots_exit=0`、`COMPLETE`；`e-mech-phase111` 保留 2 条通道重叠违例作为负结果对照。
- 阶段 B/C 18 个回合：双扫描、定位、UAV 反馈三种对照各 3 次独立重启；低位扫描命中 2 对 0（首次回波 0.161 m、可用预警约 1.0 s，逐回合见 `evidence/webots/b-scan-*/scan_stats.json`），GPS 闭环对独立真值 RMSE 0.074 m。
- 实验索引 `docs/evidence_index.md` 由 `evidence/webots/*/summary.json` 自动生成，当前 **33 个回合**，与证据目录一一对应。
- 主回合同源视频 `docs/demo/webots_full_run.mp4`（44 s / 1200×1080 / 25 fps / 1100 帧），画面里每个位置、每条事件、每个计数都来自 `f-webots-full-01` 的裁判真值与事件流；生成脚本 `docs/tools/render_replay_video.py`。
- **执行器层单车闭合**（`p-motor-b1-route`）：真实电机驱动同一台车跑完 D→W→E→L→O，通道 2.0574 m 进入、4.9504 m 清空，1/1 按期、0 违例。

## 执行器层（真实电机）结论

完整记录见 `docs/webots/PHYSICAL_LAYER.md`。摘要：

| 项 | 结论 | 证据 |
|---|---|---|
| 姿态符号 | IMU 与仿真真值同号（标准逆时针为正），差速公式方向正确 | `p-att-spin-plus`（真值 +0.558 / IMU +0.535 rad/s）、`p-att-spin-minus` |
| 撤回的早期判断 | “四轮滑移转向无法原地搓转”不成立，底盘可原地干净回转 | `p-att-spin-plus`：位置漂移 0.001 m |
| 已修缺陷 | 差速轮侧、`theta=-imu` 正反馈、±π 方向锁存、碰撞盒离地 1 cm、到点与净空互锁、机动监督缺位、驻留判据抖动 | 见 PHYSICAL_LAYER 第 3 节 |
| 单车 | 全路线闭合 | `p-motor-b1-route` |
| 八实体电机整机 | **未闭合**：11/14（0 违例）与 13/14（5 次重叠）两次尝试 | `p-motor-full-01`、`p-motor-full-02` |

八实体未闭合的根因不是控制律，是**判据与几何错位**：通道占用窗口为 `2.05 ≤ x ≤ 4.95`，而走廊墙从 `x=1.8` 到 `x=5.4`，航点 `W=(2,0)`、`E=(5,0)` 落在窗口边界内侧 5 cm。停在 W/E 的实体车按判据时而在窗内、时而在窗外，于是既可能挡住后车，也可能被记为已清空。点质量运动学后端不存在这个现象（裁判直接把平台搬到节点，`d→0`）。

修法（未实施，需改协议/场景定义，会改变已提交 26 个运动学回合的计数口径）：
1. 清空判据加口部余量（离开方向越过口部 ≥0.45 m 才释放）；
2. W/E 移出口部或增设 staging 点；
3. 占用判据改带迟滞的施密特触发（进 2.15 / 出 1.95）。

## 裁判改动的回归验证

为修复“到点驻留被稳态误差反复清零”，裁判的 `arrive_since` 取消门限加了 1.28 倍迟滞；真值采样从 `t % 500 == 0`（16 ms 步长下命中稀疏）改为按经过时间 500 ms 采样。两处改动后同配置复跑：

| 对比 | 结果 |
|---|---|
| `reverify-mech-release` vs `e-mech-release` | `(14,14,0,9,0,5,5)` 逐项一致 |
| `reverify-full2` vs `f-webots-full-01` | 全部标量字段 `scalar diffs: NONE` |

`f-webots-full-01` 的证据已用 `reverify-full2` 更新，真值轨迹由 20 点提升到 **81 点/实体**（500 ms 密度），其余字段不变。

## 仍然开放的边界

- 低矮障碍场景在物理上不可通行：障碍 `y` 跨度 0.8、中心 0.15，把 1.2 m 通道压到只剩 0.35 m 空隙，而车体宽 0.34 m。属场景移植缺陷，待改为部分遮挡后重跑，不影响运动学后端的双扫描判决。
- `web_b1_gate`、`web_b1_unmapped`、`web_long`、`web_cost` 等矩阵场景尚未生成专门世界；B-plan（Dijkstra/A*）与出口泊位检查仍以 v9 Gazebo 证据支撑，不与 Webots 秒数混算。
- C-ref / C-auto 的开关仅改变反馈来源标签，不能据此宣称 UAV 自主飞行效能；报告中按“已实现层级”写明。
- UAV 在本后端没有旋翼动力学模型，物理整机采用“六车电机 + 两机运动学”的混合配置，已在 `shutdown.json` 的 `source` 字段标注。
- 三次重启因模型确定性结果一致，登记为独立重启而非统计重复。

## 复现入口

`webots/tools/run_webots.sh <scene> <run-id>`；默认运动学后端，`GONGYU_PHYS=1` 切真实电机实验，
`GONGYU_FIELD` 无关；`GONGYU_NO_RENDER=1` 关闭主视图渲染（相机仍出图）；
`GONGYU_AERIAL=<names>` 指定留在运动学层的空中平台（物理整机需设为 `B3,R5`）。
回执写入 `~/pandaoxi/gongyu-webots-runs/<run-id>/`，摘要提交到 `evidence/webots/<run-id>/`。

## 干净目录复核（2026-11-19）

- 从提交 `f5c6e50` 全新检出到 `~/pandaoxi/gongyu_v10_verify_clean`：证据目录齐备。
- 报告 `SHA256SUMS` 两项均 OK；演示页内嵌 JSON 解析成功。
- 以新运行 ID `verify-repro-01` 从干净检出复跑 `web_b1_route`（关闭渲染），与 `b-loc-gps-01` 的场景、按期数、总数、违例数、通道进入/释放数逐项一致。

## 课程报告重建（55 页）

- 报告由 `report_v11/body.md` 单一正文生成 DOCX 与 PDF，55 页 / 29487 中文字符 / 17 图 / 40 表；目录页码由第一遍 PDF 回填，`SHA256SUMS` 两项 OK。
- 相对 v9 的增量：摘要重写、新增 1.5 节（两套仿真分工）、新增 6.12（Webots 整机主结果）与 6.13（执行器层），讨论改为 6.14，第 7 章重写，参考文献补 Webots R2025a。
- 图 16 / 图 17 由 `report_v11/src/draw_webots_figs.py` 从 `f-webots-full-01` 的真值轨迹与通道事件重绘；图内文字改用 Noto Sans CJK，修正 v10 图内拉丁字符成方框的问题。
- 正文引用的通道数字已按主回合事件流核对：B1 9.536 s 进 2.056 m、15.328 s 清 4.952 m、提前 38.976 s；此前的 10.304 / 2.0574 / 18.112 / 4.9504 属单车回合 `p-motor-b1-route`，已在报告中分开表述。

# 实验索引

本索引由 `evidence/webots/*/summary.json` 自动生成（脚本 `docs/tools/make_evidence_index.py`），
与证据目录一一对应。每个回合目录固定包含 `metrics.json`（判据输出）、`events.jsonl`（裁判事件）、
`ctl_events.jsonl`（控制器事件）、`shutdown.json`（关闭回执）、`environment.txt`（运行环境与退出码）、
`scene.sha256`（冻结场景校验和）、`summary.json`（本索引所用摘要）。

「按期」列是 `on_time / total`，即该回合实际登记的任务中按期完成数 / 登记总数。
八实体整机的登记总数应为 14；若小于 14，说明有任务未完成，具体缺失项见 `metrics.json` 的 `task_completed`。

回合总数：**33**

## B 阶段：感知、定位、规划与控制

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `b-loc-gps-01` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.511 |
| `b-loc-gps-02` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.681 |
| `b-loc-gps-03` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.585 |
| `b-loc-odom-01` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.419 |
| `b-loc-odom-02` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.426 |
| `b-loc-odom-03` | web_b1_route | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.607 |
| `b-scan-lowobs-01` | web_b1_lowobs | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.346 |
| `b-scan-lowobs-02` | web_b1_lowobs | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.404 |
| `b-scan-lowobs-03` | web_b1_lowobs | - | 0/0 | 0 | 1/1 | 0/0 | - | 2.787 |
| `b-scan-open-01` | web_b1_open | - | 1/1 | 0 | 1/1 | 0/0 | - | 4.151 |
| `b-scan-open-02` | web_b1_open | - | 1/1 | 0 | 1/1 | 0/0 | - | 3.823 |
| `b-scan-open-03` | web_b1_open | - | 1/1 | 0 | 1/1 | 0/0 | - | 3.895 |

## C 阶段：UAV 传感反馈与观测上报

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `c-auto-01` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 3.22 |
| `c-auto-02` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 2.996 |
| `c-auto-03` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 3.098 |
| `c-ref-01` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 3.441 |
| `c-ref-02` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 3.056 |
| `c-ref-03` | web_b3_target | - | 1/1 | 0 | 0/0 | 1/0 | - | 3.473 |

## D 阶段：报告时效、动态改派、机会成本

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `d-adapt` | web_medium | release | 14/14 | 0 | 5/5 | 0/9 | 9 | 112.691 |
| `d-cost-high` | web_medium | release | 14/14 | 0 | 5/5 | 9/0 | 0 | 116.127 |
| `d-report-expired` | web_medium | release | 14/14 | 0 | 5/5 | 0/9 | 0 | 117.091 |
| `d-report-ontime` | web_medium | release | 14/14 | 0 | 5/5 | 9/0 | 0 | 144.564 |

## E 阶段：共享通道机制对照

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `e-mech-phase111` | web_medium | phase111 | 14/14 | 2 | 5/5 | 9/0 | 0 | 114.614 |
| `e-mech-release` | web_medium | release | 14/14 | 0 | 5/5 | 9/0 | 0 | 125.275 |

## F 阶段：八实体整机与留出扰动

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `f-holdout-v1` | web_holdout_v1 | release | 14/14 | 0 | 5/5 | 9/0 | 0 | 125.212 |
| `f-webots-full-01` | web_medium | release | 14/14 | 0 | 5/5 | 9/0 | 0 | 125.71 |

## 执行器层：真实电机诊断分支

| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |
|---|---|---|---|---|---|---|---|---|
| `p-att-spin-minus` | - | - | 符号探针 | - | -/- | -/- | - | - |
| `p-att-spin-plus` | - | - | 符号探针 | - | -/- | -/- | - | - |
| `p-motor-b1-route` | web_b1_clear_phys | release | 1/1 | 0 | 1/1 | 0/0 | 0 | 9.505 |
| `p-motor-full-01` | web_medium_phys | release | 11/11 | 0 | 4/3 | 10/0 | 0 | 288.575 |
| `p-motor-full-02` | web_medium_phys | release | 12/13 | 5 | 8/8 | 10/0 | 0 | 261.406 |

## 其他

| 回合 | 场景 | 按期 | 违例 | 墙钟 s |
|---|---|---|---|---|
| `phys-clear-pass-03` | web_b1_clear_phys | - | - | - |
| `phys-spin-02` | web_smoke_phys | - | - | - |

## 关键回合

| 用途 | 回合 | 判据 |
|---|---|---|
| 正式整机验收 | `f-webots-full-01` | 14/14 按期、0 违例、5 次进/出、9 份报告接受 |
| 留出场景 | `f-holdout-v1` | 14/14 按期、0 违例 |
| 通道机制对照（开） | `e-mech-release` | 14/14、0 违例 |
| 通道机制对照（关） | `e-mech-phase111` | 14/14、2 违例（负结果，保留） |
| 报告时效（按期） | `d-report-ontime` | 9 接受 / 0 过期 |
| 报告时效（过期） | `d-report-expired` | 0 接受 / 9 过期 |
| 动态改派 | `d-adapt` | 0 接受 / 9 过期、9 次改派 |
| 机会成本 | `d-cost-high` | 14/14、判据改变但任务不延期 |
| 执行器层闭合 | `p-motor-b1-route` | 单车真实电机 1/1、0 违例、4.9504 m 清空 |
| 执行器层边界 | `p-motor-full-01` / `p-motor-full-02` | 11/14 与 13/14，见 `docs/webots/PHYSICAL_LAYER.md` |
| 姿态符号判定 | `p-att-spin-plus` / `p-att-spin-minus` | 真值与 IMU 同号，±0.558 / ±0.535 rad/s |


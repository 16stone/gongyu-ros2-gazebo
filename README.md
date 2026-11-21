# 共域：一条通道上的两支队伍

《无人系统导论》课程设计题目二。六辆差速地面车和两架无人机在 Webots 仿真场地执行运输和观察，共用一条窄通道。程序按车体实际清空、任务时窗和观察报告的有效期安排放行，并在共享通道上检验红蓝对抗与仿生响应阈值反制。

## 正式提交版本

**[正式报告 PDF](report_course_final/潘道熙25361130课程设计报告题目二.pdf)** 为 XeLaTeX 编译稿（含独立 Linux 仿真平台实跑结果）。可用 [SHA-256 清单](report_course_final/SHA256SUMS) 校验。将 [LaTeX 源码](report_course_final/latex/) 导入 Overleaf，主文档选 `main.tex`，编译器选 XeLaTeX。

报告第 1.4 节给出主版本与证据分层的边界，第 4 章包含基础整场与专项补验，第 5 章验证红蓝对抗与仿生防卫，第 8 章是设计复盘，附录 A 是可核对的证据入口，附录 C 是判定性调试记录。历史扩展草稿已自本分支清理，如需查阅演进过程可从标签 `v9-course` 与 Git 提交历史获取。

| 入口 | 内容 |
| --- | --- |
| [正式报告 PDF](report_course_final/潘道熙25361130课程设计报告题目二.pdf) | [报告目录](report_course_final/)含正式 PDF、XeLaTeX 源码、图表和校验清单 |
| [交稿版整机回放](docs/demo/course_final_replay.mp4) | 53 s 配套回放；[历史运动学回合回放](docs/demo/webots_full_run.mp4) 与[自包含演示页](docs/demo/webots_replay.html) 另存 |
| [Webots 复现](docs/webots/course_final_reproduce.md) | 交稿三组回合的场景、环境变量与回执读法 |
| [图模型与 Gazebo 复现](docs/reproduce.md) | 离散算例与归档整机的复现步骤 |
| [整场证据](evidence/course_final/) | normal / delay / holdout 的指标、事件、关闭回执与专项汇总 |
| [Linux 仿真补验与复现](docs/webots/amax_validation_20261120.md) | 低箱绕行、双机旋翼、跨车接管、断链和历史专项的原始回执与入口 |
| [红蓝对抗与仿生防卫专项](docs/webots/adversary_validation.md) | 通道虚占、空中重放欺骗与响应阈值撤销/帧认证八组实跑数据 |
| [逐回合索引](docs/evidence_index.md) | 33 个 Webots 专项回合；[Gazebo 归档](evidence/fp124-ent-ind-01/) 单独存放 |
| [验收状态](docs/acceptance_status.md) | 已闭合结果、执行器层诊断与开放边界 |

## 仿真平台演进

本项目早期以图模型（`source/gongyu`）和 ROS 2 / Gazebo（`source/ros`）开展调度规则筛选与多进程基线验证，随后迁入 Webots R2025a（`webots/`）完成八实体物理底盘、双高度激光雷达、四旋翼载荷、观察链路故障及红蓝对抗/仿生防卫的整场仿真。两套平台各自保留原始记录与复现入口。

## 已验证的结果

- **基础场景**采用六车电机、两机航点的混合后端。低箱、软件链路与红蓝对抗补验沿用该后端，旋翼补验使用两架电机旋翼模型。
- 正常、首份观察延迟、侦察车起点变化三组，以及两次正常复跑，均在 400 s 窗口内完成 14/14 项按期任务，通道进入与清空各 5 次，无车体占用重叠。
- 首帧同样延迟时，仅拒收过期帧的回合为 13/14，B2 未交付；开启补采后为 14/14，B2 在 314.240 s 交付。正常观察回合的 B2 交付时刻为 306.112 s。两车专项中，按实际清空放行比固定 32 s 少等 24.112 s。
- [B1 单车专项](docs/webots/B1_PHASE_B.md)：Dijkstra 与 A* 同图对照、四方向回波与近距漏检、低位雷达触发低箱前停车。
- [低箱整场](docs/webots/course_lowbox_acceptance.md)中，B1 绕行后在 133.776 s 完成原交付，整场 14/14 按期、零碰箱。
- [旋翼与接管整场](docs/webots/rotor_course_acceptance.md)中，B1 接手 B2 的第二批运输，并用 B3 新拍的相机帧放行，于 340.176 s 交付，整场 14/14 按期。
- [观察链路补验](docs/webots/observation_link_validation.md)中，随机丢帧补采与暂时断链后恢复均为 14/14。持续断链时 B2 保持等待，其余 13 项按期，通道无重叠。
- [红蓝对抗与仿生防卫专项](docs/webots/adversary_validation.md)中，红方通道虚占致 `blue1` 延后至 337.280 s、`blue2` 超期（12/14），接入响应阈值撤销后三个随机种子均恢复 14/14；红方空中重放欺骗在无认证时被 `B2` 误信放行（内容滞后 182.192 s），启用 HMAC 帧认证后拒收伪造帧并转用真帧放行；双对抗同时开启下蓝方任务全部按期且通道零重叠。

## 版本口径

`evidence/course_final/` 保留三组基础回合，补验按各自运行配置和证据目录陈述；`evidence/webots/p-motor-full-*` 是采用旧瞬时占用判据的执行器诊断分支，未闭合、不计入正式结果；`f-webots-full-01` 是运动学筛选回合；第 6、7 章的 Gazebo 归档与图模型按各自平台时间单独陈述。跨平台只比较行为是否复现，不并列秒数。

## 作者与工具说明

本课程设计的选题构思、系统架构设计、红蓝对抗与仿生协同规则建模、实验方案设计与主要工程实现由**潘道熙（16stone）**完成；开发过程中借助 AI 编程助手作为辅助工具，用于脚本编写辅助、调试定位与文档文字润色，全部关键逻辑、仿真参数与实验数据均经过个人核对与实跑复验。

# 共域：一条通道上的两支队伍

《无人系统导论》课程设计题目二。六辆差速地面车和两架无人机在 Webots 仿真场地执行运输和观察，共用一条窄通道。程序按车体实际清空、任务时窗和观察报告的有效期安排放行。

## 正式提交版本

**`report_course_final/` 是唯一提交版本**：PDF 与 DOCX 由同一份 [`body.md`](report_course_final/body.md) 生成，11 月 20 日定稿 PDF 共 50 页，含 AMAX 补验，`SHA256SUMS` 可校验。终版用 Word 从同源正文生成的 DOCX 导出。Linux 可用 `python report_course_final/src/build_report.py` 重建（需 python-docx、LibreOffice、poppler）；导出字体和分页取决于环境。

报告第 1.4 节给出主版本与四层证据的边界，第 4 章包含基础整场与新增补验，第 7 章是设计复盘，附录 A 是可核对的证据入口，附录 C 是判定性调试记录。`report_v11/` 是 55 页历史扩展稿，只作方案演进记录，**不作为提交版本**。

| 入口 | 内容 |
| --- | --- |
| [正式报告 PDF](report_course_final/潘道熙25361130课程设计报告题目二.pdf) | [报告目录](report_course_final/)含 Word、同源正文、图表、构建脚本和校验清单 |
| [交稿版整机回放](docs/demo/course_final_replay.mp4) | 53 s 配套回放；[历史运动学回合回放](docs/demo/webots_full_run.mp4) 与[自包含演示页](docs/demo/webots_replay.html) 另存 |
| [Webots 复现](docs/webots/course_final_reproduce.md) | 交稿三组回合的场景、环境变量与回执读法 |
| [图模型与 Gazebo 复现](docs/reproduce.md) | 离散算例与归档整机的复现步骤 |
| [整场证据](evidence/course_final/) | normal / delay / holdout 的指标、事件、关闭回执与专项汇总 |
| [AMAX 补验与复现](docs/webots/amax_validation_20261120.md) | 低箱绕行、双机旋翼、跨车接管、断链和历史专项的原始回执与入口 |
| [逐回合索引](docs/evidence_index.md) | 33 个 Webots 专项回合；[Gazebo 归档](evidence/fp124-ent-ind-01/) 单独存放 |
| [验收状态](docs/acceptance_status.md) | 已闭合结果、执行器层诊断与开放边界 |

## 已验证的结果

- **基础场景**采用六车电机、两机航点的混合后端。低箱与软件链路补验沿用该后端，旋翼补验使用两架电机旋翼模型。
- 正常、首份观察延迟、侦察车起点变化三组，以及两次正常复跑，均在 400 s 窗口内完成 14/14 项按期任务，通道进入与清空各 5 次，无车体占用重叠。
- 首帧同样延迟时，仅拒收过期帧的回合为 13/14，B2 未交付；开启补采后为 14/14，B2 在 314.240 s 交付。正常观察回合的 B2 交付时刻为 306.112 s。两车专项中，按实际清空放行比固定 32 s 少等 24.112 s。
- [B1 单车专项](docs/webots/B1_PHASE_B.md)：Dijkstra 与 A* 同图对照、四方向回波与近距漏检、低位雷达触发低箱前停车。
- [低箱整场](docs/webots/course_lowbox_acceptance.md)中，B1 绕行后在 133.776 s 完成原交付，整场 14/14 按期、零碰箱。
- [旋翼与接管整场](docs/webots/rotor_course_acceptance.md)中，B1 接手 B2 的第二批运输，并用 B3 新拍的相机帧放行，于 340.176 s 交付，整场 14/14 按期。
- [观察链路补验](docs/webots/observation_link_validation.md)中，随机丢帧补采与暂时断链后恢复均为 14/14。持续断链时 B2 保持等待，其余 13 项按期，通道无重叠。

## 版本口径

`evidence/course_final/` 保留三组基础回合，补验按各自运行配置和证据目录陈述；`evidence/webots/p-motor-full-*` 是采用旧瞬时占用判据的执行器诊断分支，未闭合、不计入正式结果；`f-webots-full-01` 是运动学筛选回合；第 5、6 章的 Gazebo 归档与图模型按各自平台时间单独陈述。跨平台只比较行为是否复现，不并列秒数。

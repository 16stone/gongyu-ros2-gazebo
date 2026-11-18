# 八实体巡检与报告中继 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. Steps use checkbox syntax. One final branch review; do not start a reviewer per task.

**Goal:** 形成六地面车、两无人机的真实任务场景，R3/R4各有实际巡检、报告交付和返程任务，并能用实际消息替代R5为报告投递而进行的迁移。

**Architecture:** 复用World/PhysicalWorld、Network和已有本机任务回执；新增地面巡检控制器与R5本地报告路线选择。策略只读自身报告、实际收到的中继可用性和公开地图；报告来源由裁判的实际巡检记录验证，站点验收及回执均走同一网络。六实体历史分支、正在运行的53e1392物理M2不改变。

**Tech Stack:** Python标准库、现有ROS2 Jazzy/Gazebo/Nav2；不新增依赖。分支feature/g2-relay，起点53e1392。

**Spec:** C:/Users/ZhuanZ/Documents/ChatGPT/无人系统导论/02_参考文档/创新定案_20261028/共域_执行方案.md，第1、3.3、阶段5节；总体创新方案_共域.md。本文只落实G2巡检/报告/具身接口，三种靶标与留出矩阵另立实现，不能用中继模式代替那三类策略。

## Global Constraints

- 机器人队属、硬件能力公开；每车最多持有一份载荷，无人机不运输地面载荷，R3/R4没有运输接口。
- 六实体与八实体共用数据格式、决策接口和裁判。旧四车结果只作为工程经验，不作为新方案的实验数据。
- 每个新增实体至少有一个需实际到位的巡检任务和一个依赖实际传输的报告交付，不靠提高机器人数量获得“复杂度”。
- 新增任务不会读取裁判真值；失败、未恢复和约束违例均可查询。
- ROS域83物理运行串行；当前phase25两回合及归档结束后才启用八实体物理尝试。图开发在隔离分支独立进行。
- 新场景是发展场景，不是实体数单因素对照或未调参留出；所有时间是未测发展估计，实际偏差保留。

## Review Focus

1. 报告未实际巡检、来源被改写或重复转发：不得提前/重复验收；由Task1反例覆盖。
2. 站点已收到但本机尚未实际收到ACK：本机完成状态仍未知；由Task1网络回执反例覆盖。
3. 中继过期、正移动或会突破自身返程：拒绝承诺，不能抹掉自身任务；由Task2覆盖。
4. 中继缺席或消息丢失：R5合法自行移动投递或保留明确失败，不虚构送达；由Task2覆盖。
5. 八实体命名空间/帧和泊位：6套Nav2、2套飞控全部实际就绪才开始使命；由Task3配置及实际回合覆盖。

## 场景与本地选择

发展卡从physical_M2_development_v1派生。R3/R4的payload_interface=false，与role字段无关。新增N0=(8,-3)、PN=(9,-3)、RN=(12,-5)，S0=(8,-13)、PS=(9,-13)、RS=(12,-11)，各容量1；边为N0-PN、PN-RN、S0-PS、PS-RS，仅地面。1m边12s、sqrt(13)m边26s是转弯/驻留在内的保守发展估计；不是实测。原六实体时间、能力、tau6和任务期限保留。

R3/R4各执行：实际到PN/PS巡检；在该区生成独立报告交付任务的实测记录；移动至RN/RS后真实投递站点并收到回执；在自身返程预算允许时提供中继；返原起点实际完成返程检查。巡检期限60s、报告期限70s，返程期限R3=86s或110s、R4=130s（两张发展卡预先声明）。每实体3任务，共14任务。

本队站点移到(18,-8,.3)，R5在F_R仍可直传，在H_R不能直传，在K_R可直传；RN/RS同时连接H_R与站点。因此R5可以依据实际收到的中继可用性选择4跳报告/回执路径，或自己飞到K_R投递、确认后回H_R。只有已知报告/回执结果才更新本机任务状态。R5不读取R3/R4私有期限，只读其明示available_until；中继端另核对自己的真实位置、忙碌和返程余量。

此站点/任务变化让中继有实际替代作用，也意味着不能把六实体旧场景和八实体的全队完成率差异解释为机器人数量效应。另存同一通信几何的六实体自传参照，只比较R5动作与报告交付，不比较不同任务分母的总率。

### Task 1: 本机巡检报告、来源验证与硬件边界

**Files:** Modify gongyu/model.py、gongyu/world.py；Test tests/test_inspection_relay.py。
**Interfaces:** LocalView最后新增inspection_reports: tuple=()；World仅在G2标志下把实际inspect完成生成的task_id/source_id/region/sampled_at/report_id暴露给对应本机。六实体旧自动直投行为保持原样。G2站点验收要与已实际生成的报告完全匹配；ACK回到源本机时才写local_results。

- [x] 写反例：inspect未完成没有可发报告；伪造来源/时间/区域拒绝；重复转发只验收一次；站点已收到但ACK未达时本机仍未知；R3即使role改为transport也拒绝load/unload。
- [x] 在隔离分支运行反例观察失败，最小实现并运行核心回归；保留红绿结果。
- [x] 提交本机报告/硬件边界；不在策略里查询issued/global completed表。

### Task 2: 有自身任务的地面巡检/中继与R5自传替代

**Files:** Create gongyu/patrol.py、freeze_g2.py；Modify gongyu/policies.py、gongyu/m2.py（仅G2构造路径）；Test tests/test_g2.py。
**Interfaces:** GroundInspector(actor,commands,policy)持有自身巡检/报告/返程工作流；RelayProvider继承Provider，消费自己的inspection_reports及实际中继offer，命令deliver_own_report等待本机ACK后再继续。g2_controllers(card,policy)替换R3/R4/R5；其余用原M2控制器。

- [ ] 写完整图反例：8实体/14任务、R3/R4均实际迁移并投递、R5实际经一个中继收回ACK；中继忙碌/过期不承诺；R3私有期限变化可让R5选择R4；无中继时R5移动K_R自传，不注入结果。
- [ ] GroundInspector只在实际位于RN/RS且非忙碌、可履行自身返程时发offer，承诺4跳报告/回执的实际驻留窗口；转发使用原报告和新消息ID。R5按自身任务按期量/逾期/主动作业/完成时刻选择，未知中继只能作为待查询，不能当已承诺。
- [ ] 冻结两张发展卡和同几何六实体自传参照后运行图预检，保存完整输入、候选、消息链、所有任务分母与失败；图通过不记物理通过。
- [ ] 核心与ROS相关回归通过后提交。发布/冻结前做一次整分支独立审查，重要问题只作一次红绿修复。

### Task 3: 六Nav2/双飞控具身与证据

**Files:** Modify ros/fleet_episode.py、ros/audit_fleet_episode.py；检查现有ros/fleet.launch.py、ros/prepare_mission_world.py；Test ros/tests/test_fleet_scene.py、ros/tests/test_mission_scene.py（增加八实体夹具）。
**Interfaces:** actor集合来自card/config；允许且检查(4 ground,2 air)或(6 ground,2 air)，传感器/定位/起飞/反馈门槛仍逐实体。PhyscialWorld沿用实际泊位、方向出口保护与任务验收，新增主体不进入蓝队候选的运输接口。

- [ ] 配置反例验证R3/R4各自模型、命名空间、scan/peer_scan、TF、Nav2参数、8个初始泊位无冲突；消除使命/审计路径中固定6的计数。
- [ ] 旧6实体和新8实体配置均通过；运行完整核心/ROS必要回归，不安装新依赖。
- [ ] 当前物理批次终止且所有自有组清空后，单独冻结八实体场景/源码/输入哈希；运行一次真实就绪、完整使命及独立审计，保存报告中继事件触发的原生截图和失败扫描。
- [ ] 记录真实14任务、R5路线/收到ACK及中继自身返程情况；失败保留，不能以ACTIVE或报告已排队代替送达。用新终态更新交付索引。

后续：三类靶标+非响应参照、未调参18回合及强P2补充、正式三张主图/原生视频、>=3500字原生Windows课程报告分别依赖本阶段真实证据；本计划不提前勾选这些验收。

Ruling（实现中澄清）：R3/R4的一次实际区域巡检同时生成独立的报告交付凭据，报告仍须真实送达和ACK；删除原型中重复的第二次inspect作业。report_from链接需校验同一actor/mode/region。为维持原型同样4s的最短返程余量，R3默认期限由88调整为86s（减少重复2s服务），在任何G2物理和正式预检前声明。旧原型cfad837仅单元/发展测试，不作为新卡结果；版本G2-development-v2。

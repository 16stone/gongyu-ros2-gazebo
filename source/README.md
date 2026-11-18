# 共域 / Gongyu

本工程用两支各有自身任务的空地团队，检查通道竞争、报告时效和组织重构如何影响任务交付。已接入确定性图模型和ROS 2/Gazebo物理反馈后端：六实体为四车两机，八实体为六车两机。旧四车工程保持隔离，不并入新实验分母。

活动源码：`/home/zhuanz/projects/gongyu`。Windows交付：`C:/Users/ZhuanZ/Documents/ChatGPT/无人系统导论/01_工作区/共域`。当前状态以`evidence/active_execution.json`和具体终态为准，`progress.md`保留了早期未完成状态与排错历史。

## 已有证据

| 内容 | 入口 | 证据范围 |
|---|---|---|
| P0—P3与增强P2 | `evidence/phase02_v4/` | 10张题卡40轮和6轮增强P2；图模型 |
| 诊断、真实交接、剩余任务修复 | `phase03_geometry_v2/`、`phase05_online_v1/`、`phase06_rolling_v2/`（均在evidence下） | 两批任务在动作边界修复，不是任意任务和运动中抢占 |
| 六实体图模型M2 | `evidence/phase07_m2_v1/` | 4条件×服务关/开×5策略40轮，含成交、拒绝、迟到失效 |
| 六实体物理M1 | `evidence/phase20_M1_matrix_setup/state.json`、`phase24_matrix_audit_setup/summary.json` | 六次独立启动，执行/启动失败分别保留 |
| 六实体物理M2 | `evidence/phase25_contact_forecast_setup/physical_summary.json` | 互利、拒绝各一次400s，均8/8按期；不是统计优势 |
| 八实体实际任务和中继 | `evidence/phase32_G2_setup/physical_summary.json` | 14/14按期，R3/R4实际巡检/报告/返航，R5实际经R4送达并收到ACK；墙钟截断387.478s，非完整400s |
| 八实体完整物理窗口 | `evidence/phase46_clearance_setup/physical_summary.json` | 完整400s、14/14按期、68个独立完成窗口无越界、采样地面包络无重叠；出口净空与物理航点修复后的发展验证 |
| 三类靶标和非响应参照 | `evidence/phase33_target_modes_development/` | 同任务/预算下2条件×4模式8轮图发展回合；代理分数不等于实际蓝方损失 |
| 未调参留出 | `evidence/phase34_holdouts/completed.json` | 18轮P2/P3及9轮P2_equal，无执行错误；9张卡上P3与增强P2交付相同 |
| 录像与同步面板 | Windows `演示/八实体G2/共域_同步回放.html` | 2099张实际相机帧完整解码，按原仿真时间戳同步；有标明倍率的1×/2×/4×播放 |

2026-11-01的phase38 GPU复测因D入口阻塞后R1导航中止，12/14按期；phase43使命前定位种子错误、phase44西口被停车阻塞而中断13/14、phase45无效抽象折线加载拒绝均保留。phase46使用a9c84e6的新发展布局、D接近FIFO和物理专用航点，完整400s、14/14按期及独立审计均已通过：蓝方183.460/242.846s，R1=229.830s；无未释放通道或记录的约束违例。任务、期限、车速、保护与图模型几何不变；物理布局和路径已改，不能当GPU单因素比较或未调参留出。新版回放在Windows `演示/八实体G2_D入口修复/共域_同步回放.html`，2154帧、28张原生截图，Edge30s/360s和视觉检查通过。16项当前工程验收通过；课程报告按用户要求暂缓，现有结构计划不算报告交付。

## 实现链

`world.py`负责任务验收、消息和资源。图模型按冻结边时长推进；`PhysicalWorld`必须等执行器反馈才确认实际到位/服务完成。`planning.py`、`remaining.py`、`adaptive.py`用本机任务、已送达状态和公开地图比较有限候选。P2逐块严格改善，P3允许联合改变，P2_equal允许等值移动及两个固定起点，共用总预算；未实际收到的周期计划仅作条件预测。

`m2.py`执行真实请求/报价/接受/时隙提交/报告/验收回执。`patrol.py`给R3/R4自身巡检、报告与返航任务；二者无运输接口，来源巡检、站点验收和源主体ACK分别核对。R5用实际收到的报价选择中继或自行移动投递。

`modes.py`区分独立任务、互惠、受约束对抗和高层非响应参照。入口观测通过Network实际送达，只包含连续停留实体的ID和时间，不含蓝方任务、载荷或内部期限。对抗先检查本队按期/移动预算；实际配额不足的回合不删除。

`ros/`给每车建立独立激光、AMCL、TF和Nav2；无人机采用多旋翼动力学及位置外环，不是悬空Nav2小车。所有初始区域、位置误差、低速连续驻留门槛通过后才开始使命，独立真值另行审计。

新的物理D配置在最后接近段按实际就绪顺序排队，E→W→D连续持有通行权，直到真实成功且连续驻留后释放。该公共执行资源不读取对手私有任务。`physical_delivery_waypoint`只改变物理W→D的中间目标；图模型固定边长及预测仍保持原样，新增排队/行程不能冒称已重新校准。

真正任务发布时间是`task.release_ms`（缺省0）。历史`red_release_ms`也用于固定基线起步/预先预约，不能一概解释成任务尚不可执行，否则会错误禁止合法取消预约和提前改道。

## 复现

WSL Ubuntu-24.04工程根目录：

```bash
cd /home/zhuanz/projects/gongyu
python3 -m unittest discover -s tests
source /opt/ros/jazzy/setup.bash
python3 -m unittest discover -s ros/tests
```

目标模式冻结时175项核心/23项ROS通过；D修复分支当前184项核心/24项ROS通过，包含实际题卡加载、FIFO、真实驻留释放、泊位净空和地图边界回归；各计划独立审查与失败记录另存。仅在代码或环境变化需要核实时重复。

例如复现一张已冻结图模型卡，输出必须用新目录：

```bash
python3 -m gongyu.run --case evidence/phase34_holdouts/bypass_position_17.json \
  --blue P3 --red task --seed 0 --out evidence/manual_holdout_P3_new
```

`--seed 0`是原图执行器种子；扰动种子17及逐任务偏移已固化在`holdout_design`，不应重新生成后冒称同次复现。正式批次每轮有输入、manifest、events、decisions、metrics和轨迹。已有runner/plan使用固定路径，禁止盲目重跑和覆盖历史证据。

物理运行两终端需共享`ROS_DOMAIN_ID=83`、`GZ_PARTITION=gongyu_fleet_episode_20261030`、`GZ_IP=127.0.0.1`和同一`GONGYU_FLEET_SCENE`。先启动`ros/fleet.launch.py`，再用`python3 -m ros.fleet_episode 新输出目录 冻结场景 --policy P3`。实际传感器、定位、有效TF、导航ACTIVE、起飞及初始到位门槛逐项执行，新目录由使命客户端创建。正式runner只管理自己的进程组，保留清理回执，不清理其他会话进程。

本机可在单次进程环境中选择NVIDIA渲染，不修改全局设置：

```bash
MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA glxinfo -B
```

需要`glxinfo`与实际Gazebo日志均显示D3D12/NVIDIA才能记为GPU运行；写了环境变量本身不构成证明。

## 速度与结论边界

Nav2地面限速0.26m/s；题卡`ground_speed=0.5`不直接控制Nav2，物理预测使用单独冻结的`travel_time_ms`。phase32移动中位数约0.23—0.26m/s，实时因子约0.194，因此实时观看慢约5.2倍。录像按仿真时间保存，演示倍率不改变实验数据。提高车速需要重查转弯、制动、泊位和行程标定。

独立到位限值为地面0.25m、空中水平0.30m/高度0.20m、低速0.10m/s及连续1s；本机更紧的检查与独立真值分别报告。采样包络无重叠不等于连续全机安全证明。

载荷仍是符号任务，观察/遮挡/无线采用冻结几何模型，不代表相机识别或无线实测。移动预算为冻结边时长累计，不是能耗。策略只验证有限任务族，不宣称任意任务、任意对手、真实硬件或分布式安全隔离上的普遍性能。原生截图像素不编辑；Windows只替换文件名冒号，交付SHA256索引用于核对文件。

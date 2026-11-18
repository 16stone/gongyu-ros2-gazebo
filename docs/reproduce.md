# 复现说明

## 图模型算例

从仓库根目录进入 `source` 并用 Python 3运行。`runs/g-m1-check` 应为新的输出目录。

~~~sh
cd source
python -m gongyu.run --case scenarios/G_M1.json --blue P3 --red task --seed 0 --out ../runs/g-m1-check
~~~

检查生成的 `metrics.json`，两队各 3 项任务按期，`constraint_violations` 为空。目录还包含决策、事件、轨迹和任务时间线。该检查运行图模型。

## Gazebo 整机

归档主运行环境为 Ubuntu 24.04（WSL2）、ROS 2 Jazzy、Nav2 和 Gazebo Harmonic。需要 ROS 2 与 Gazebo 的桥接、`nav2_minimal_tb3_sim`、PyYAML 及 Gazebo Transport 13 / Messages 10 Python 绑定。仓库根目录的 `sha256sum -c PROJECT.SHA256` 可核对冻结输入的字节。

下列命令在已配好依赖的个人 Ubuntu 环境运行。先用冻结题卡生成本地场景，再由项目的 runner 启动 Gazebo、Nav2 和任务客户端。runner 固定使用 ROS 域 83 与对应的 Gazebo 分区，同一环境内串行运行。

~~~bash
source /opt/ros/jazzy/setup.bash
cd source
run_dir=$(mktemp -d)
python3 -m ros.prepare_mission_world \
  ../scenes/scene_medium_independent/source_scenario.json \
  "$run_dir/medium_independent"
GONGYU_TOPOLOGY=entities GONGYU_MECH=joint \
  python3 -m ros.fleet_runner --scene "$run_dir/medium_independent" \
  --out "$run_dir/result" --policy P3 --feedback-mode truth
~~~

检查 `result_launch/shutdown.json` 的 `status` 是否为 `COMPLETE`，再从 `result/metrics.json` 核算按期任务与约束违例。`result/events.jsonl` 的 `channel_enter` 记录通道资源持有的起点，`channel_cleared` 记录释放。

本仓库保留已有主回合回执和历史录屏。GitHub 归档时已运行图模型算例并验证场景生成，整机数据来自课程归档中的原始记录。 [主回合证据](../evidence/fp124-ent-ind-01)

本次在 Windows 上执行了 292 项核心测试，289 项通过，2 项因 Linux 专用条件跳过。测试 test_no_route_verdict_rechecks_on_the_clock_alone 的模拟对象缺少泊位占用计数，该项报错。冻结快照保留原样。

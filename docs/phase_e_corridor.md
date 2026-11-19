# 阶段 E 共享通道对照

## 同版图模型

以 `8689cc699c9909baab4c5d3b8cea1e1efd37e24e` 的冻结卡、P3、seed 0 跑 20 个回合。中绕行与长绕行分别使用已有独立及竞争配置，平移独立卡用于复验。每张卡运行 `phase111`、`release`、`rolling`、`joint`，四臂的任务、行动预算、信息权限、资源容量、裁判和源码文件哈希一致。中、长绕行各自的独立与竞争卡只改变 `id` 和 `target_mode`。

| 场景 | 蓝方 1 / 2 批交付 (s) | 红方 1 / 2 批交付 (s) | B2 入口到持有 (s) | 蓝方按期 | 红方按期 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 中绕行独立、长绕行独立 | 255 / 305 | 196 / 74 | 40 | 3/3 | 11/11 |
| 中绕行竞争、长绕行竞争 | 274 / 324 | 224 / 74 | 59 | 3/3 | 11/11 |
| 平移独立 | 265 / 315 | 206 / 84 | 40 | 3/3 | 11/11 |

每臂有 5 次、每次 48 s 的固定图遍历，没有通道违例、预约缩短或泊位等待事件。四种机制的任务时间逐项相同。独立转为竞争时，蓝方两批各晚 19 s，红方首批晚 28 s、期限余量从 54 s 降为 26 s，按期数未变。入口到持有取本车最后一条入口到位事件至持有起点，含调度等待与其他先决条件。

## 放行规则与下游准入

`phase111` 在共享源码里保留入口互斥与名义预约。实际完成通行后，`release` 缩短已经使用且仍有效的预约。图模型在固定名义时刻完成遍历，留不出缩短余量。现行 `joint` 的排序项取当前节点空位，在一次排序中各候选共享该值。物理实现对 D 到达区的准入另行检查，`phase111` 到 `joint` 均运行这项检查。

用冻结中绕行生成后的卡作确定性的 `PhysicalWorld` 反馈夹具，依次提供到位、低速驻留和匹配动作完成。前车在 5.000 s 清空，两臂同步执行 2 s 的通道间隔。名义预约到 48.000 s，B2 在 50.000 s 进入。开启 `release` 后，预约端点变为 5.000 s，D 已清空时 B2 在第一次探测的 7.200 s 进入。D 正被 B1 使用时，两种开启配置都保持通道空闲，B1 在 15.000 s 到达验收并释放 D 后，B2 方进入。本夹具验证实际程序的放行条件，输入是受控反馈样本。

历史 Webots 运动学对照中的 `phase111` 关闭了入口互斥，`release` 开启互斥。0 与 2 条违规用于验证互斥的作用。Webots 电机世界采用 `footprint_serial_dispatch` 和足迹清空判据。共享源码的名义预约缩短、Webots 运动学入口互斥及电机串行派车各有独立的执行路径。

## Gazebo 历史原始记录复算

`fs-mechoff-ind-01` 与 `fs-mechon-ind-01` 均为 `phase123-wslgpu`、中绕行独立、P3、truth、完整窗。两份关闭回执中记录的源码哈希逐项相同。两臂均 14/14、零记录违例。开臂是组合配置 `joint`。

| 指标 | phase111 | joint |
| --- | ---: | ---: |
| B2 通道资源持有起点 (s) | 243.466 | 236.854 |
| B2 地面车中心首次采样进入墙内区 (s) | 250.290 | 244.204 |
| B2 裁判释放通道资源 (s) | 267.524 | 261.282 |
| 蓝方 1 批交付 (s) | 245.572 | 239.198 |
| 蓝方 2 批交付 (s) | 298.556 | 295.480 |
| 红方 1 批交付 (s) | 187.784 | 183.448 |
| 红方 2 批交付 (s) | 44.874 | 46.360 |

开臂五次窗口缩短分别为 22.030、21.222、23.026、25.080、23.572 s，合计 114.930 s。B2 开始持有提前 6.612 s，中心首次进墙内区提前 6.086 s，交付提前 3.076 s。前一车辆 B1 释放后，B2 仍记录到 D 归 B1 使用的等待。两臂均有反复采样的 `physical_arrival_held`，每条记录是一次拒绝派车判断。红方 2 批晚 1.486 s，仍按期。单组配对可核对时序，不能从中拆出各机制的整机绩效贡献。

墙内区依据冻结场景生成规则取 x∈[2.35, 4.65] m、y∈[-0.50, 0.50] m。独立坐标流记录的占用采样时刻共 5091 个与 5177 个，每个时刻仅有一辆地面车中心位于墙内区，均处于对应的裁判资源持有时段。采样判据评价车辆中心与墙内区的关系。通道资源持有从运动请求前便开始。

同源码长绕行独立 `fs-hold-long-ind-01` 为完整窗，14/14、零记录违例、5 个窗口合计缩短 114.082 s。4659 个地面车中心占用采样时刻均归属单车，B2 在 298.636 s 交付，余量 51.364 s。长绕行存档支持该配置可执行。整机收益对照来自中绕行的历史组合开关，单独 `release` 的整机效果仍无物理配对。

## 复算入口

在本工作树根目录执行。外部路径为原始运行和结果目录，新图回合需要新目录。

```bash
EVIDENCE="$HOME/pandaoxi/gongyu-enhance-evidence/corridor"
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
mkdir -p "$EVIDENCE/graph"
(
  cd source
  for scene in medium_independent medium_adversarial long_independent long_adversarial shifted_independent; do
    for mech in phase111 release rolling joint; do
      GONGYU_MECH="$mech" nice -n 12 python3 -m gongyu.run \
        --case "../scenes/scene_$scene/source_scenario.json" --blue P3 --seed 0 \
        --out "$EVIDENCE/graph/$scene-$mech"
    done
  done
)
PYTHONPATH=source nice -n 12 python3 docs/tools/phase_e_probe.py \
  scenes/scene_medium_independent/scenario.json > "$EVIDENCE/feedback-fixture.json"
mkdir -p "$EVIDENCE/archived-gazebo/extracted"
for archive in "$EVIDENCE"/archived-gazebo/*.audit.tar.gz; do
  nice -n 15 tar -xzf "$archive" -C "$EVIDENCE/archived-gazebo/extracted"
done
nice -n 12 python3 docs/tools/phase_e_audit.py "$EVIDENCE/graph" \
  "$EVIDENCE/archived-gazebo/extracted" "$EVIDENCE/archived-gazebo/scenes" > "$EVIDENCE/timeline.json"
```

`timeline.json` 保留逐任务期限、各车持有/清空、预约可用约束、出入口等待的采样边界及原始文件哈希。`archived-gazebo/` 的三份原始记录摘档及两张冻结卡由 `SHA256SUMS` 校验。摘档源为 AMAX 已保存的历史课程目录 `gongyu_course_archive_20261115/C_workspace/10_构建工作区/_冲分_20261110/evidence`。

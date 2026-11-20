# B1 低矮障碍、入口对准及扫描覆盖补验

2026-11-20，AMAX 上使用 Webots R2025a、物理差速底盘和独立裁判。门口对照与未建图避障各臂三次独立重启，世界随机种子 0。同一臂的主要结果一致，试验用于复核执行链和明确边界。

## 未建图低障碍

同一场景、同一 A*、同一起终点。低箱不进初始地图，停在箱前后才依据低位扫描点和 GPS/IMU 位姿更新占据区。扫描推断保守补上箱体背面，规划器重新生成跟踪点。对照开着低位雷达，检测后停车，保持原有安全动作。

| 条件 | 低位触发 | 裁判结果 | 实际轨迹 / m | 最小车体保守净距 / m |
| --- | --- | --- | ---: | ---: |
| 检测后停车 | 5.472 s，0.420 m | 6.496 s 安全停车，0/1 | 1.992 | 0.378 |
| 检测后绕行 | 5.472 s，0.420 m | 5.792 s 改道，33.248 s 完成末端驻留，1/1 | 7.387 | 0.124 |

两臂均零障碍接触。先在 `web_b1_phaseb_lowobs` 完成匹配对照，再在同一物理几何的 `web_b1_unmapped` 各重复三次。绕行来自低位传感和车体电机执行。这个试验给固定静态低箱留出了侧向空间，旧窄道中只余 0.35 m 的阻塞布局仍保留为几何失败案例。

## 入口几何

`web_b1_gate` 中，裁判发布当前通行授权和 B2 已下发的参考线段。B1 比较该线段离对准点的最近距离与 0.65 m 阈值。B2 同样用仿真电机行驶。预计净距与实跑最小净距分别来自参考线段和两车独立真值。

| 条件 | 对准点至同伴参考路径 / m | 实际选用对准点 | 入场时偏航绝对值 / rad | 整车清空 / s | 交付 / s | 两车最小保守净距 / m |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| 只按授权，安全参考线段 | 1.370 | 否 | 0.356 | 13.168 | 17.568 | 0.991 |
| 加对准，安全参考线段 | 1.370 | 是 | 0.075 | 16.080 | 21.296 | 0.798 |
| 加对准，冲突参考线段 | 0.541 | 否，走原路线 | 0.356 | 13.168 | 17.568 | 0.495 |

九次试验均按期到终点，无障碍接触及车体包络重叠。安全参考线段下，对准动作让入场角度更接近通道方向，本试验中增加了通过时间。冲突参考线段下，车仍能沿原两点进入路线完成任务。

## 高度和遮挡

同一静止位置、同一目标底座。改变目标高度，另设高目标前加遮挡板。每行扫描 16 帧，按仿真真值坐标归属回波。

| 箱体目标 | 主雷达命中帧 | 低位雷达命中帧 |
| --- | ---: | ---: |
| 0.27 m，无遮挡 | 0/16 | 16/16 |
| 0.36 m，无遮挡 | 16/16 | 16/16 |
| 0.65 m，无遮挡 | 16/16 | 16/16 |
| 0.65 m，同高板遮挡 | 0/16 | 0/16 |

遮挡板两雷达均 16/16 命中。这四个回合检验指定前向位置和高度；旧版实测的车后低位与近距盲区继续按对应条件陈述。

## 回执和复现

[回执复核结果](../../evidence/b1_followup_20261120/summary.json)包含 21 个回合及各自源码提交。原始包包含裁判真值、点云、控制器消息、指标和源文件散列。解压后，以下命令按独立轨迹核验回执和源码散列。

```bash
python3 -B webots/tools/verify_b1_followup.py /absolute/path/to/extracted-runs
```

Linux 上从仓库根目录运行。输出目录用绝对路径，重新运行时更换目录或回合 ID。

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
export GONGYU_PHYS=1 GONGYU_NO_RENDER=1 GONGYU_SEED=0
suffix=20261120-01
GONGYU_B1_BYPASS=0 bash webots/tools/run_webots.sh web_b1_unmapped b1-unmapped-stop-$suffix
GONGYU_B1_BYPASS=1 bash webots/tools/run_webots.sh web_b1_unmapped b1-unmapped-bypass-$suffix
GONGYU_B1_GATE_ALIGN=0 GONGYU_B1_GATE_PEER=clear bash webots/tools/run_webots.sh web_b1_gate b1-gate-direct-$suffix
GONGYU_B1_GATE_ALIGN=1 GONGYU_B1_GATE_PEER=clear bash webots/tools/run_webots.sh web_b1_gate b1-gate-clear-$suffix
GONGYU_B1_GATE_ALIGN=1 GONGYU_B1_GATE_PEER=conflict bash webots/tools/run_webots.sh web_b1_gate b1-gate-conflict-$suffix
for name in low mid high occluded; do
    bash webots/tools/run_webots.sh web_b1_phaseb_coverage_height_$name b1-height-$name-$suffix
done
```

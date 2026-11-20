# B1 低箱绕行整场验收

AMAX 上的 Webots R2025a，CPU 物理仿真、Mesa 软件渲染。场景 `web_medium_phys_lowbox` 沿用原八实体任务卡和截止时间，B3 与 R5 沿用航点运动学，六辆地面车由仿真电机驱动。低矮箱体放在东侧开阔段，B1 的初始局部地图中没有该箱体。

## 验收结果

回合 `b1-full-lowbox-20261120-04`，源码 `a6e2de0`，400.000 仿真秒完整关闭。整场 14/14 项按期，通道 5 进 5 清，零车体通道占用重叠，零箱体接触。B1 与箱体的最小保守车体净距为 0.123 m。

| 事件 | 仿真时刻 / s |
| --- | ---: |
| B1 低位雷达发现前方低箱，触发停车 | 117.824 |
| B1 停稳后用新扫描更新局部地图并改道 | 118.240 |
| R1 依次驶往东侧三个通道外预对准点 | 120.000、123.312、129.696 |
| B1 绕过低箱，完成 `blue1` 的原卸货点驻留 | 133.776 |
| R1 完成 `red1` | 233.856 |
| B2 完成 `blue2` | 300.944 |

R1 在原释放时刻之后才预对准。B1 完成交付前，R1 只能到东侧通道外准备点，随后才获得原通行名额并继续执行。预对准期间 B1 与 R1 的最小中心距为 3.033 m。R1 距 250 s 截止还有 16.144 s。独立裁判的[验收摘录](../../evidence/b1_full_lowbox_20261120/accepted/verification.json)、[完整指标](../../evidence/b1_full_lowbox_20261120/accepted/result/metrics.json)和[事件流](../../evidence/b1_full_lowbox_20261120/accepted/bus/events.jsonl)可交叉核查。

## 诊断回合

| 回合 | 可观测问题 | 处理 |
| --- | --- | --- |
| [首轮](../../evidence/b1_full_lowbox_20261120/initial_failure/result/metrics.json) | 11/14 按期。B1 停车后局部规划阻塞，后续三项运输均未完成 | [短诊断](../../evidence/b1_full_lowbox_20261120/scan_diagnostic/bus/ctl_events.jsonl)抓取停稳前后的扫描与位姿，确认箱体侧面回波的厚度被重复外推，误封卸货点 |
| [修正占据估计](../../evidence/b1_full_lowbox_20261120/side_depth_fix_failure/result/metrics.json) | B1 已完成绕行，碰箱一次，R1 晚 4.272 s，整场 13/14 按期 | 将 B1 最后一段进入低箱附近的速度上限降到 0.18 m/s，并等测得速度不高于 0.04 m/s 再转向 |
| [加减速和停车约束](../../evidence/b1_full_lowbox_20261120/braking_fix_late/result/metrics.json) | 无碰箱，R1 晚 1.360 s，整场 13/14 按期 | 允许 R1 到通道外预对准，任务与截止时间保持原值 |

这次通过的低箱在开阔段，有足够侧向绕行空间。旧窄通道只余 0.35 m 的几何条件单独保留。

## 复现

在装有 Webots R2025a 和 Xvfb 的 Linux 上，从仓库根目录运行。确保输出根目录是绝对路径，回合编号尚未使用。

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1 \
  bash webots/tools/run_webots.sh web_medium_phys_lowbox course-lowbox-replay
python3 -B webots/tools/verify_course_lowbox.py "$GONGYU_RUNS_ROOT/course-lowbox-replay"
```

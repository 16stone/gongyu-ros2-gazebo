# Webots 八实体跨车接管试验

## 2026-11-20 实跑结果

两个回合均关闭于 400.000 仿真秒，14/14 项按期，通道 5 进 5 清，零车体占用重叠。接管回合由 B1 在 **330.976 秒**完成第二批交付，距 350 秒截止还有 **19.024 秒**。

| 回合 | 实际交付车 | `blue2` 完成时刻 / s | 源码与原始回执 |
| --- | --- | ---: | --- |
| 正常对照 | B2 | 290.336 | `90c4f44` · [指标](../../evidence/blue2_handoff_20261120/control/result/metrics.json) · [关闭回执](../../evidence/blue2_handoff_20261120/control/shutdown.json) |
| B2 退让 | B1 | 330.976 | `f1b3d24` · [指标](../../evidence/blue2_handoff_20261120/handoff/result/metrics.json) · [关闭回执](../../evidence/blue2_handoff_20261120/handoff/shutdown.json) |

| 接管回合的事件 | 仿真时刻 / s |
| --- | ---: |
| B2 停稳并释放未完任务 | 247.152 |
| B1 控制器发出接手确认 | 247.328 |
| 裁判收到确认，更新通道名额和卸货点归属 | 247.344 |
| B1 在原中转点完成取货驻留 | 257.536 |
| B1 由东向西进入通道 | 313.120 |
| B1 整车清空通道 | 324.320 |
| B1 在原卸货点停稳并完成交付 | 330.976 |

[裁判事件流](../../evidence/blue2_handoff_20261120/handoff/bus/events.jsonl) · [B1 控制器确认](../../evidence/blue2_handoff_20261120/handoff/bus/handoff_B1.jsonl) · [验收脚本输出](../../evidence/blue2_handoff_20261120/handoff/verification.json)。归档的 `scene.sha256` 采用相对仓库路径，散列值与运行机原始清单一致。

## 试验条件

在 AMAX 上用 Webots R2025a、Xvfb 和 Mesa 软件渲染运行 `web_medium_phys`。六辆地面车由仿真电机驱动，B3 和 R5 按航点运动。沿用八实体、14 项任务、400 秒回合和 `blue2` 的 350 秒截止时间。

打开 `GONGYU_BLUE2_HANDOFF=1` 后，裁判在第二批运输发车前让 B2 从东侧中转点驶入退让位。裁判按真值确认 B2 到位并停稳，释放同一个 `blue2` 任务，向已完成第一批运输的 B1 发出接管请求。B1 控制器通过消息总线确认后，裁判把本轮由东向西通行的名额和西侧卸货点交给 B1。有效观察到达后，B1 经中转点驻留、穿越通道，在原目的地停稳并完成交付。

本试验验证固定中转点上的任务改派和仿真地面车执行。货物交接沿用中转点驻留的任务模型。退让由试验注入，接手车为预先指定的 B1。

## 复现

在 Linux 上从仓库根目录运行。已有环境用 `GONGYU_WEBOTS_HOME` 和 `GONGYU_XVFB_ROOT` 指定 Webots 和 Xvfb 目录。输出根目录用绝对路径，每次使用新的运行 ID。

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
export GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1
GONGYU_BLUE2_HANDOFF=1 bash webots/tools/run_webots.sh web_medium_phys blue2-handoff-replay
python3 -B webots/tools/verify_blue2_handoff.py "$GONGYU_RUNS_ROOT/blue2-handoff-replay"
```

验证脚本交叉检查控制器确认、裁判事件、物理车辆通道清空、唯一交付回执、350 秒截止与 400 秒完整窗口。开启接管的回合应返回 B1 完成 `blue2`，整场 14/14 按期，车体通道 5 进 5 清，零占用重叠。

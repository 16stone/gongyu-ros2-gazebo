# 八实体观察链路故障试验

Webots R2025a，`web_medium_phys`，原任务卡和带车体判空的串行放行。地面车走电机模型，两架无人机在航点运动学层，B3 相机帧经过软件链路送给 B2。两个回合均为源码 `7533002`、种子 1、400.000 s 完整窗口。链路注入发生在观察帧的计划送达时间，丢失后等到该帧时效截止，再申请一份时间更新的帧。

| 工况 | 观察链路结果 | 按期 | 通道进/清 | 占用重叠 |
| --- | --- | --- | --- | --- |
| 随机丢包率 0.25 | 第一帧 240.928 s 丢失，245.920 s 超时，246.976 s 收到新帧并放行。B2 305.248 s 交付 | 14/14 | 5/5 | 0 |
| 观察链路持续断开 | 27 帧被丢弃，其中 26 帧在窗口内等到超时。B2 未收到放行或运动指令，`blue2` 缺失 | 13/14 | 4/4 | 0 |

0.25 是注入参数。随机臂这次只有两次送达尝试，用于核对故障与恢复顺序。持续断开的 13/14 是预登记的安全降级判据。注入只覆盖 B3 观察到 B2 放行这一链路。无线信道、多消息拥塞与真实环境射频干扰需有实物链路才能评价。

- 随机丢包：[裁判事件](../../evidence/observation_link_20261120/random_loss/bus/events.jsonl)、[指标](../../evidence/observation_link_20261120/random_loss/result/metrics.json)
- 持续断链：[裁判事件](../../evidence/observation_link_20261120/blackout/bus/events.jsonl)、[指标](../../evidence/observation_link_20261120/blackout/result/metrics.json)
- [验收摘录](../../evidence/observation_link_20261120/summary.json)

在 Webots 与 Xvfb 路径已设置的 Linux 仓库根目录运行：

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
export GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1 GONGYU_SEED=1
GONGYU_OBSERVATION_LOSS_RATE=0.25 bash webots/tools/run_webots.sh web_medium_phys obs-loss-v2
GONGYU_OBSERVATION_BLACKOUT_MS=0:400001 bash webots/tools/run_webots.sh web_medium_phys obs-blackout-v2
```

核对 `bus/events.jsonl`、`result/metrics.json` 与 `shutdown.json`。断链组应无 B2 运动指令、无 `blue2` 交付，`missing_task_ids` 保留该任务。两组用车轮与车体真实仿真反馈验收通道动作。

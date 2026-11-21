# 红蓝对抗与仿生防卫专项试验

在 Webots R2025a（`web_medium_phys`，400.000 s 完整仿真窗口，六辆电机驱动地面车与两架运动学无人机）上，面向同一共享单车通道验证两类红方对抗策略与两类蓝方防卫机制的闭环交互。

## 1. 对抗与防卫机制实现

- **红方通道虚占（`GONGYU_ADVERSARY=hoard`）**：`R1` 在 `R2` 完成后抢先获取通道通行授权，但在入口外故意滞留至 `145.000 s`（任务卡释放时间为 `120.000 s`），阻塞排在后面的蓝方运输车 `B1`、`B2`。
- **红方空中侦听与重放欺骗（`GONGYU_ADVERSARY=spoof`）**：`R5` 完成自身巡察返场后飞抵监听点 `(12.0, 5.0)`（距蓝方观察机 `B3` 约 `3.61 m <= 8.0 m` 截获半径，距蓝方中转泊位约 `5.25 m <= 10.0 m` 注入半径），录制 `B3` 至少 `20 s` 前的旧相机帧；监测到 `B2` 发起观察请求后，伪造当前仿真时间戳重放注入 `observation_B3.jsonl`。
- **蓝方响应阈值撤销（`GONGYU_DEFENSE=threshold`）**：参考社会性昆虫固定响应阈值分工模型，后车 `B1` 在通道外等待且持有人闲置时每秒累积刺激 $s$，并按期限余量缩放阈值 $\theta \in [1.0, 6.0]\ \text{s}$，以概率 $p = s^2/(s^2+\theta^2)$ 发起挑战。裁判通过真值运动监督器 `IdleMonitor` 核验持有人在通道外、非站点驻留且连续 `2.0 s` 内平动 $\le 0.05\text{ m}$、转角 $\le 0.05\text{ rad}$ 后，才撤销其授权并顺延放行后车。
- **蓝方帧认证防卫（`GONGYU_DEFENSE=auth`）**：`B3` 为每帧观察报告计算涵盖发送方、采样时刻、图像特征签名与帧字节数的 HMAC-SHA256 摘要；`ObservationGate` 拒绝校验不通过的伪造帧并触发 `observation_unauthenticated` 事件，随后接收 `B3` 新发布的合法签名帧。

## 2. 八组实跑结果汇总

基础环境变量均为 `GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1 GONGYU_FIRST_OBSERVATION_DELAY_MS=1000`。

| 工况 | 种子 | 按期任务 | 通道进/清 | 重叠 | B1 / R1 / B2 交付时刻 (s) | 对抗与防卫核查 |
| --- | --- | --- | --- | --- | --- | --- |
| `regress_normal`（基线回归） | 0 | 14/14 | 5/5 | 0 | 125.392 / 239.360 / 306.112 | 与主基线逐毫秒一致，B2 在 240.928 s 正常放行 |
| `hoard_off`（虚占无防） | 0 | 12/14 | 6/6 | 0 | 337.280 / 290.208* / 392.912* | `R1` 滞留至 145 s，致 `blue1` 延后 211.888 s、`blue2` 超期（350 s 限），且 `R1` 东口刮擦导轨自身超期 |
| `hoard_thresh_s0`（虚占+阈值） | 0 | 14/14 | 6/6 | 0 | 128.848 / 244.976 / 296.560 | `B1` 于 85.696 s（$s=4.0, \theta=4.405, p=0.4519$）撤销 `R1` 授权，全员按期 |
| `hoard_thresh_s1`（虚占+阈值） | 1 | 14/14 | 6/6 | 0 | 128.848 / 244.976 / 296.560 | `B1` 于 85.696 s（$s=4.0, \theta=4.405, p=0.4519$）撤销 `R1` 授权，全员按期 |
| `hoard_thresh_s2`（虚占+阈值） | 2 | 14/14 | 5/5 | 0 | 126.224 / 240.544 / 286.784 | `B1` 于 82.672 s（$s=3.0, \theta=4.455, p=0.3119$）撤销 `R1` 授权，全员按期 |
| `spoof_off`（欺骗无防） | 0 | 14/14 | 5/5 | 0 | 121.920 / 234.544 / 282.976 | `R5` 于 234.624 s 重放 53.440 s 旧帧；`B2` 于 235.632 s **误信伪造帧放行**（真实滞后 182.192 s） |
| `spoof_auth`（欺骗+认证） | 0 | 14/14 | 5/5 | 0 | 125.392 / 239.360 / 306.112 | `B2` 于 239.424 s 拦截伪造帧（`unauthenticated_frames=1`），240.928 s 改用真帧放行 |
| `combined_def`（双对抗+双防卫） | 0 | 13/14 | 5/5 | 0 | 127.776 / 251.584* / 304.752 | 83.680 s 撤销 `R1` 授权，251.648 s 拦截伪造帧，蓝方任务全部按期；红方 `red1` 超 250 s 限 1.584 s |

注：带 `*` 为超出该项任务期限（`red1` 期限 250 s，`blue2` 期限 350 s）。

## 3. 证据入口与复现命令

- 归档摘要：[summary.json](../../evidence/adversary_20261121/summary.json) · [SHA256SUMS](../../evidence/adversary_20261121/SHA256SUMS)
- 各回合目录：`evidence/adversary_20261121/{regress_normal,hoard_off,hoard_thresh_s0,hoard_thresh_s1,hoard_thresh_s2,spoof_off,spoof_auth,combined_def}/`

在已配置 Webots R2025a 与 Xvfb 路径的 Linux 仓库根目录复现：

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
export GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1 GONGYU_FIRST_OBSERVATION_DELAY_MS=1000

bash webots/tools/run_webots.sh web_medium_phys adv-regress-normal
GONGYU_ADVERSARY=hoard bash webots/tools/run_webots.sh web_medium_phys adv-hoard-off
GONGYU_ADVERSARY=hoard GONGYU_DEFENSE=threshold GONGYU_SEED=0 bash webots/tools/run_webots.sh web_medium_phys adv-hoard-thresh-s0
GONGYU_ADVERSARY=spoof bash webots/tools/run_webots.sh web_medium_phys adv-spoof-off
GONGYU_ADVERSARY=spoof GONGYU_DEFENSE=auth GONGYU_BLUE_KEY=gongyu-blue-2026 bash webots/tools/run_webots.sh web_medium_phys adv-spoof-auth
GONGYU_ADVERSARY=hoard,spoof GONGYU_DEFENSE=threshold,auth GONGYU_BLUE_KEY=gongyu-blue-2026 GONGYU_SEED=0 bash webots/tools/run_webots.sh web_medium_phys adv-combined-def
```

校验单元逻辑与归档完整性：

```bash
python3 -B -m unittest discover -s webots/tests -v
(cd evidence/adversary_20261121 && sha256sum -c SHA256SUMS)
```

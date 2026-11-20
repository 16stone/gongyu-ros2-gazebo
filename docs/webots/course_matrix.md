# Webots 历史实验矩阵补跑

三组专项在 AMAX 的 Webots R2025a 上独立关闭。地面车沿用课程双轮电机底盘和 GPS/IMU 控制器。裁判读取仿真真值，到点、低速并连续驻留 0.8 s 才确认任务完成。三组每臂各启动三个独立进程，均固定世界随机种子为 0，用来检查同配置复现。

## 长绕行与放行规则

R1 走名义长 28 m 的折线绕行，B1、B2 先后通过同一窄通道。两臂都要求 B1 的整个车体包络清空后才让 B2 出发。固定窗口臂还要等到 32 s，实际清空臂在清空当步派车。B2 截止时间为 65 s，回合完整运行 140 s。保持入口互斥的固定窗口采用历史试验臂名 `phase111`。历史八实体运动学全关试验与这里的物理固定窗口各自有对应的执行路径。

三个重启的主要时刻一致。B1 在 7.888 s 清空。实际清空组当步放行 B2，在 22.928 s 完成交付，3/3 按期。固定窗口组在 32.000 s 放行，B2 到 72.304 s 才交付，超过 65 s 截止，2/3 按期。两组均无通道重叠。R1 在两组均于 92.064 s 交付。固定窗口组有 −0.045 m 最低保守侧壁余量，提示车体靠近了边界，墙体接触需另查。

结果见[试验汇总](../../evidence/webots_matrix_20261120/summary.json)与[逐回合原始文件](../../evidence/webots_matrix_20261120/runs)。每个回合都实际跟踪了 R1 的三个绕行目标，折线的 28 m 是名义路径长度，真值积分长度另列在指标中。

## 出口泊位准入

B1 在 B2 的目的泊位停留，从 28 s 开始驶向自己的下一目的地。两臂都先让 B2 在入口外对准，并采用实际清空放行。开启出口检查后，B2 还要等待 B1 离开泊位，真值中心与该泊位至少相距 0.70 m 才放行。回合持续至少 65 s。

`vehicle_envelope_overlap_samples` 是双车中心距低于 0.56 m 的采样数量，采样间隔为 16 ms。侧壁诊断采用 0.28 m 保守包络。负余量表示对应姿态超出该圆包络判据。若需判断碰撞，还要测量与墙体的物理接触。

六次均 2/2 按期。不检查泊位时，B2 在 7.888 s 出发，记录到 266 个车间保守包络重叠采样。检查泊位时，B2 等到 30.176 s 才出发，63.216 s 交付，车间重叠采样为零。检查组最小保守墙侧余量为 −0.041 m。

无预对准的[诊断回合](../../evidence/webots_matrix_20261120/diagnostic)另存。诊断中口部检查开启后 B2 正确等待，但截止时还未驶过通道。加入两臂共用的入口、出口过渡点后重新做配对。

## 支援的机会成本

B1 有一项交付任务，B2 可代为交付，并必须完成自己的返回任务。两臂使用同一场地、位置和控制器。唯一变化是 B2 返回期限，低约束 50 s，紧约束 23 s。支援方案用路线距离、0.40 m/s 预测速度及每段 4 s 的到点裕量，比较交付收益、额外活跃时间和返场截止时间。支援预测返回为 28.225 s，独自返回预测为 12.839 s，交付时间净节省预测为 13.750 s，额外活跃时间预测为 11.386 s。低约束由 B2 实际去目的地后返程，紧约束由 B1 去交付、B2 直接返程。

每臂的三次主要结果一致。低约束组 B2 在 8.160 s 代交付，32.192 s 返回。紧约束组 B1 在 19.072 s 交付，B2 在 16.896 s 返回，比自身截止早 6.104 s。两组均 2/2 按期。

## 重跑及核验

在 Linux 中配置 `GONGYU_WEBOTS_HOME`（Webots 目录）和 `GONGYU_XVFB_ROOT`（Xvfb 用户态目录），从源码检出根目录运行。使用一个未占用的绝对输出根目录。长绕行和机会成本的实跑源码为 `3519799`，出口成对试验为 `24550fc`。若需复现相同源文件哈希，请在各自的检出运行对应命令。

```bash
export GONGYU_PHYS=1 GONGYU_NO_RENDER=1 GONGYU_SEED=0
export GONGYU_RUNS_ROOT="$PWD/runs/webots-matrix-replay"
for repeat in 01 02 03; do
  for mech in release phase111; do
    GONGYU_MECH="$mech" bash webots/tools/run_webots.sh web_long "web-long-$mech-$repeat"
  done
  for cost in low high; do
    GONGYU_COST="$cost" bash webots/tools/run_webots.sh web_cost "web-cost-$cost-$repeat"
  done
done

# For the exit-check checkout, point GONGYU_RUNS_ROOT to the same absolute path.
for repeat in 01 02 03; do
  for check in off on; do
    GONGYU_MATRIX_EXIT_CHECK="$check" bash webots/tools/run_webots.sh web_medium_exit "web-exit-$check-$repeat"
  done
done

# Run from the final archive commit.
python3 -B webots/tools/verify_course_matrix.py "$GONGYU_RUNS_ROOT"
```

每个原始回合附场景和运行源文件 SHA256、事件、定点轨迹和关闭回执。场景清单路径已改为仓库相对路径，哈希仍以 AMAX 原始清单为准。完整归档可用 `sha256sum -c SHA256SUMS` 核对。

# 八实体多旋翼实跑

## 正常观察回合实测

回合 `rotor-course-20261120-01`，运行源码 `d79cc82`。400.000 仿真秒完整关闭，八实体均由仿真执行器驱动，14/14 项任务按期，通道 5 进 5 清，记录车体占用重叠 0 次。

| 证据 | 时刻 / s 或数值 |
| --- | --- |
| B3 空中巡察验收 | 4.256 s |
| R5 空中巡察、巡逻、落地返场 | 4.208, 12.832, 25.424 s |
| B3、R5 采样真值最高点 | 1.9161、1.9170 m |
| B3 应地面请求采样，标记像素数 | 239.520 s、526 |
| B2 获授权，收到图像的年龄 | 240.544 s、1.024 s |
| B3 返场落地 | 243.024 s |
| B2 第二批交付 | 315.120 s，距 350 s 截止 34.880 s |

[验证汇总](../../evidence/rotor_course_20261120/normal/verification.json) · [独立真值与指标](../../evidence/rotor_course_20261120/normal/result/metrics.json) · [裁判事件](../../evidence/rotor_course_20261120/normal/bus/events.jsonl) · [相机报告](../../evidence/rotor_course_20261120/normal/bus/observation_B3.jsonl)。模型使用固定地标和持续供电假设。场景清单归档为相对路径，SHA-256 值与 AMAX 原始记录一致。

`web_medium_rotor_phys` 复用 `web_medium_phys` 的六车、电机控制器、任务卡、路线和车体包络通道裁决。生成器将原场景的两架运动学飞机替换成单机验证用四旋翼刚体，加入 B3 基地标记。B3、R5 都使用 GPS、惯性单元和陀螺仪，原单机的位置与姿态环输出四个有符号的螺旋桨转速。裁判以三轴运动真值、速度和驻留判定到位，独立记录返场落地。红方飞行任务的验收是到位与返场，光学任务验证对应 B3。

B3 初次到达 F 后识别下方标记，沿 F–K–H–K–F 飞行，在 F 保持待命。B2 准备发车时，裁判发出采样请求。B3 的下视相机重新拍摄并检查标记，从 RGB 像素生成签名，保存证据帧。只有这次请求之后采集的有效报告可以授权 B2 出发。授权后 B3 落地。R5 按 F_R–K_R–H_R–K_R–F_R 飞行，在基地落地后完成返场任务。

## 复现

在具备 Webots R2025a、Xvfb 和 Mesa 软件渲染的 Linux 上，从仓库根目录运行。以绝对路径指定运行目录，并为每次试验使用新回合号。

```bash
export GONGYU_RUNS_ROOT="$PWD/runs"
python3 -B webots/tools/generate_rotor_course.py
GONGYU_PHYS=1 GONGYU_AERIAL="" GONGYU_NO_RENDER=1 \
  bash webots/tools/run_webots.sh web_medium_rotor_phys rotor-course-replay
python3 -B webots/tools/verify_rotor_course.py "$GONGYU_RUNS_ROOT/rotor-course-replay"
```

验收脚本检查 400 s 完整窗口、14 项任务全部按期、通道 5 进 5 清、零车体占用重叠、两机四旋翼输出及独立飞行轨迹、返场落地，以及 B3 证据帧和 B2 放行事件的时序与签名。地面碰撞判据仍是原通道占用规则，本次条件为正常观察和固定机位。

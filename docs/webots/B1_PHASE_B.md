# B1 单车感知、定位与导航实验

| 编号 | 布局与唯一切换 | 固定条件与验收 |
| --- | --- | --- |
| B-scan-cover | 静止 B1，前、后、左、右四个立体板，加一个低位近障 | 两具单层雷达同时记录点云，逐目标查方向、距离及近距遮挡 |
| B-scan-low | 同一未知低箱体，单独切换低位雷达是否进入保护条件 | A*、基础地图、目标、反馈控制、电机、障碍与初姿态固定。记录首次命中、首次停车、近似车体净距、物理接触和到位 |
| B-plan-open / narrow | 各布局内对照 Dijkstra / A* | 同一 0.05 m 栅格、0.34 m 膨胀、八邻域和禁斜切规则、起终点、简化和跟踪。搜索扩展数、计算耗时、原始栅格长度与真值轨迹长度单独计。小车在目标真值 0.12 m 内驻留 0.768 s 时计验收 |
| B-loc-replay | 相同轨迹比较车轮编码器积分和轮速积分加已知墙面扫描地图匹配 | 对齐同一仿真毫秒，姿态误差按 Z-up 方向测量。同一 GPS/IMU 跟踪生成轨迹，地图定位在回放计算 |

webots/config/b1_experiment.json 冻结两扫描平面、障碍、目标和判据。生成器复用原 B1 的两驱差速底盘与前后球轮。在实验起始姿态下，雷达局部安装高度为 0.20 m 和 0.105 m，车体原点标称距地 0.12 m，所以平面名义距地为 0.32 m 与 0.225 m。0.27 m 低箱顶在二者之间。激光 X 方向前置到车体原点前 0.24 m。180 点/圈与 16 ms 采样。控制器读取传感、规划并通过电机推进，裁判读取仿真真值、检查物理接触和到位驻留。未建图低箱测试使用前向 ±16°、0.42 m 的锁存停车条件。

Webots R2025a 以 Lidar.getPointCloud() 保存设备坐标。两台为 fixed、圆柱投影、单层、2π。配置满足 numberOfLayers < verticalFieldOfView × horizontalResolution / fieldOfView，该版本默认垂直视场是 0.2 rad。低于 minRange 的对象可能遮挡后方但不报告自身距离。[Webots R2025a LiDAR](https://github.com/cyberbotics/webots/blob/R2025a/docs/reference/lidar.md)

AMAX 上运行，已安装 Webots R2025a 和私有 Xvfb。每次使用新回合目录。示例分别运行窄入口的两种算法，保留 bus/ 扫描点、命令、接触、轨迹、result/ 指标及环境回执。

```bash
export GONGYU_RUNS_ROOT="$HOME/pandaoxi/gongyu-enhance-evidence/ugv/runs"
export GONGYU_PHYS=1 GONGYU_NO_RENDER=1 GONGYU_B1_LOW=1
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 LP_NUM_THREADS=2
for algorithm in dijkstra astar; do
  GONGYU_B1_PLANNER="$algorithm" \
    flock -w 240 "$HOME/pandaoxi/gongyu-enhance-sim.lock" \
    nice -n 10 bash webots/tools/run_webots.sh web_b1_phaseb_narrow "repro-narrow-$algorithm"
done
```

开阔为 web_b1_phaseb_open，低箱为 web_b1_phaseb_lowobs（同一算法分别用 GONGYU_B1_LOW=0/1），静止覆盖为 web_b1_phaseb_coverage。本实验使用 GPS/IMU 跟踪。轮式里程计加扫描地图的效果以同轨迹回放评价。

## Gazebo B1 与 Webots B1 的接口对应

在 Gazebo 的 source/ros/worlds/nav_calibration.sdf 中，B1 主雷达 hls_lfcd_lds 在所属链节局部 (-0.064, 0, 0.15) m，360 点、5 Hz、名义 6.28 rad。低位 peer_lidar 的传感器与固定关节位姿均可在该 SDF 核对，传感器在 peer_scan_link 局部 (0.08, 0, 0.06) m，480 点、5 Hz、覆盖 -π 至 π。局部量必须叠加所属链节和车体安装高度，才能与世界坐标中的扫描平面比较。主数据送 /B1/scan，低位送 /B1/peer_scan。场景 B1 配置 scenes/scene_medium_independent/config/nav2_B1.yaml 中，AMCL 读取 scan；两个 Costmap 分别用主雷达障碍层和低位 peer_layer 做标记与清除；碰撞监视器两路都读。Navfn 参数 use_astar: false 选择 Dijkstra。该 Gazebo 配置只作为本实验的设计参照，Webots 使用此卡定义的 0.34 m 二值膨胀与八邻域搜索。

两种算法共用同一堆、步长、候选生成与终止规则。A* 用八邻域距离作启发；Dijkstra 用零启发。八邻域斜走要求两侧相邻正交栅格都可用。相同栅格最短长度对应 104 个直步和 16 个斜步，窄入口的障碍膨胀仍留下满足该下界的可行路径。命令目标由同一个可见性简化步骤生成，因此原始栅格长度、简化目标序列和仿真实际轨迹各自留档。

轮式预测直接积分编码器增量。扫描校正将主雷达点投到预测位姿的平面，关联近邻已知墙面，用带轮式先验的鲁棒点到墙残差更新平移和偏航。平行墙面对沿走廊方向的约束弱，端部及侧方标记可增加不同方向的约束。初始位置和航向来自冻结实验卡，日志只在最终误差核验时使用裁判真值。

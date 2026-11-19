# Webots 最终方案的复现

实测环境为 Linux 上 Webots R2025a，Xvfb 与 Mesa CPU 软件渲染，Python 3.10。将 Webots 和 Xvfb 环境路径分别配置为 GONGYU_WEBOTS_HOME 和 GONGYU_XVFB_ROOT。默认目录按系统中的安装位置调整。运行器为每个回合新建显示和输出目录，仿真关闭后释放自己的显示进程。

从本目录用 Bash 运行：

    export GONGYU_RUNS_ROOT="$PWD/runs"
    export GONGYU_PHYS=1 GONGYU_AERIAL=B3,R5 GONGYU_NO_RENDER=1
    GONGYU_FIRST_OBSERVATION_DELAY_MS=1000 bash webots/tools/run_webots.sh web_medium_phys new-normal
    GONGYU_FIRST_OBSERVATION_DELAY_MS=7300 bash webots/tools/run_webots.sh web_medium_phys new-delay
    GONGYU_FIRST_OBSERVATION_DELAY_MS=1000 bash webots/tools/run_webots.sh web_holdout_v1_phys new-holdout

每次用新运行 ID。检查回执的 full_window、状态、on_time、total、missing_task_ids、late_task_ids 和 occupied_at_close。通道的成对事件与 B2 放行在 bus/events.jsonl。查看 source.commit、scene.sha256 和 source.sha256 确认源与场景。

快速软件复核：

    python3 -B -m unittest discover -s webots/tests -v
    sha256sum -c PROJECT.SHA256

Gazebo 基线从 source/ros/fleet_runner.py 进入，依赖 ROS 2、Nav2 与 Gazebo。最终报告以原始记录验证的后端与范围为准。

# 工作方式：本地指令 → amax 执行 → GitHub 交付

## 角色

- **指令端**：WorkBuddy 会话。用户在这里下指令，Agent 拆解任务并回报结果。
- **执行机**：amax（`ssh amax-pi05`，经本机 WSL Ubuntu-24.04 转入）。仿真、测试、报告生成等计算任务全部在 amax 上运行；本机不再跑计算、不再生成交付压缩包。
- **交付端**：本仓库 `main` 分支。提交即交付，不反复打 ZIP 包。

## 标准闭环

1. 在 amax 仓库目录 `git pull --ff-only`。
2. 在 amax 上执行任务；原始大体积输出留在 `~/pandaoxi/gongyu-amax-sim/`，或放在 `evidence/<run-id>/runs/` 由 `.gitignore` 排除。
3. 只把可复现的小文件提交进 `evidence/<run-id>/`：`summary.json`、指标、事件、回执等；必要时附一份简短说明。
4. `git add` 明确路径 → `git commit -m "<run-id>: <做了什么> / <关键结论>"` → `git push`。
5. 回报 commit 短 SHA 与本仓库链接，交付完成。

## 目录约定

- `source/`：冻结源码（任务规划、消息、岗位与资源调度、ROS 2 / Gazebo 入口）。
- `scenes/`：冻结场景卡，不随临时实验改动。
- `evidence/<run-id>/`：按回合归档的证据摘要；原始大文件不提交。
- `docs/`：复现说明、本工作约定。
- `PROJECT.SHA256`：冻结输入校验索引；改动冻结输入时须同步更新。

## 身份与密钥

- amax 仓库路径：`/home/liujingzhi/pandaoxi/gongyu-ros2-gazebo`
- 专用部署密钥：`~/.ssh/id_ed25519_gongyu_github`（仅授权本仓库，具写权限）
- 仓库已设 `core.sshCommand` 指向该密钥；提交身份为 `gongyu-amax <gongyu-amax@users.noreply.github.com>`。
- amax 到 GitHub 的 HTTPS / curl 超时不通，必须走 SSH remote。

## 清理策略

旧副本不作为交付物堆积在工作区：

1. 可再生临时副本（ZIP 解压目录、`_验收解压_*`、`fullscore_verify_*`、旧快照）先登记「路径 → 做过什么 → 可从哪里再生成」。
2. 清理前先列清单给用户确认，并先备份到 amax；确认后再删本地。
3. `01_最终交付/` 内的终版件保留，不自动删除。
4. 历史 release（`v9-course` 的 PDF / 视频 / ZIP）是快照，除非明确要求不重写。

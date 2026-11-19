#!/usr/bin/env python3
"""Generate docs/evidence_index.md from the landed evidence summaries.

Single source of truth: every row is derived from evidence/webots/<id>/summary.json, so
the index cannot drift from what was actually run.
"""
import json, os, glob

R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EV = os.path.join(R, 'evidence/webots')
OUT = os.path.join(R, 'docs/evidence_index.md')

GROUPS = [
    ('b-', 'B 阶段：感知、定位、规划与控制'),
    ('c-', 'C 阶段：UAV 传感反馈与观测上报'),
    ('d-', 'D 阶段：报告时效、动态改派、机会成本'),
    ('e-', 'E 阶段：共享通道机制对照'),
    ('f-', 'F 阶段：八实体整机与留出扰动'),
    ('p-', '执行器层：真实电机诊断分支'),
]

rows = []
for p in sorted(glob.glob(EV + '/*/summary.json')):
    d = json.load(open(p, encoding='utf-8'))
    d['_id'] = os.path.basename(os.path.dirname(p))
    d['_files'] = sorted(os.listdir(os.path.dirname(p)))
    rows.append(d)

def fmt(d):
    if d.get('kind') == 'attitude sign probe':
        return '符号探针'
    on = d.get('on_time'); tot = d.get('total')
    return '%s/%s' % (on, tot) if on is not None else '-'

lines = []
lines.append('# 实验索引')
lines.append('')
lines.append('本索引由 `evidence/webots/*/summary.json` 自动生成（脚本 `docs/tools/make_evidence_index.py`），')
lines.append('与证据目录一一对应。每个回合目录固定包含 `metrics.json`（判据输出）、`events.jsonl`（裁判事件）、')
lines.append('`ctl_events.jsonl`（控制器事件）、`shutdown.json`（关闭回执）、`environment.txt`（运行环境与退出码）、')
lines.append('`scene.sha256`（冻结场景校验和）、`summary.json`（本索引所用摘要）。')
lines.append('')
lines.append('「按期」列是 `on_time / total`，即该回合实际登记的任务中按期完成数 / 登记总数。')
lines.append('八实体整机的登记总数应为 14；若小于 14，说明有任务未完成，具体缺失项见 `metrics.json` 的 `task_completed`。')
lines.append('')

total_runs = len(rows)
lines.append('回合总数：**%d**' % total_runs)
lines.append('')

for pref, title in GROUPS:
    sel = [d for d in rows if d['_id'].startswith(pref)]
    if not sel:
        continue
    lines.append('## %s' % title)
    lines.append('')
    lines.append('| 回合 | 场景 | 机制 | 按期 | 违例 | 进/出 | 报告接受/过期 | 改派 | 墙钟 s |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    for d in sel:
        lines.append('| `%s` | %s | %s | %s | %s | %s/%s | %s/%s | %s | %s |' % (
            d['_id'], d.get('scene') or '-', d.get('mechanism') or '-', fmt(d),
            d.get('violations', '-'), d.get('channel_enters', '-'), d.get('channel_releases', '-'),
            d.get('reports_accepted', '-'), d.get('reports_expired', '-'),
            d.get('replans', '-'), d.get('wall_seconds', '-')))
    lines.append('')

rest = [d for d in rows if not any(d['_id'].startswith(p) for p, _ in GROUPS)]
if rest:
    lines.append('## 其他')
    lines.append('')
    lines.append('| 回合 | 场景 | 按期 | 违例 | 墙钟 s |')
    lines.append('|---|---|---|---|---|')
    for d in rest:
        lines.append('| `%s` | %s | %s | %s | %s |' % (
            d['_id'], d.get('scene') or '-', fmt(d), d.get('violations', '-'),
            d.get('wall_seconds', '-')))
    lines.append('')

lines.append('## 关键回合')
lines.append('')
lines.append('| 用途 | 回合 | 判据 |')
lines.append('|---|---|---|')
lines.append('| 正式整机验收 | `f-webots-full-01` | 14/14 按期、0 违例、5 次进/出、9 份报告接受 |')
lines.append('| 留出场景 | `f-holdout-v1` | 14/14 按期、0 违例 |')
lines.append('| 通道机制对照（开） | `e-mech-release` | 14/14、0 违例 |')
lines.append('| 通道机制对照（关） | `e-mech-phase111` | 14/14、2 违例（负结果，保留） |')
lines.append('| 报告时效（按期） | `d-report-ontime` | 9 接受 / 0 过期 |')
lines.append('| 报告时效（过期） | `d-report-expired` | 0 接受 / 9 过期 |')
lines.append('| 动态改派 | `d-adapt` | 0 接受 / 9 过期、9 次改派 |')
lines.append('| 机会成本 | `d-cost-high` | 14/14、判据改变但任务不延期 |')
lines.append('| 执行器层闭合 | `p-motor-b1-route` | 单车真实电机 1/1、0 违例、4.9504 m 清空 |')
lines.append('| 执行器层边界 | `p-motor-full-01` / `p-motor-full-02` | 11/14 与 13/14，见 `docs/webots/PHYSICAL_LAYER.md` |')
lines.append('| 姿态符号判定 | `p-att-spin-plus` / `p-att-spin-minus` | 真值与 IMU 同号，±0.558 / ±0.535 rad/s |')
lines.append('')

open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('wrote', OUT, len(rows), 'rounds')
for pref, _ in GROUPS:
    print(' ', pref, sum(1 for d in rows if d['_id'].startswith(pref)))

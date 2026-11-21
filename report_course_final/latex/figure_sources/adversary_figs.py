"""Draw Fig. 17 and Fig. 18 (red-blue adversary chapter) from the archived summary.

Input : evidence/adversary_20261121/summary.json (repository root)
Output: report_course_final/latex/figures/fig17.pdf, fig18.pdf
"""
import json
import os
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.lines import Line2D

work = Path(__file__).resolve().parent
repo = work.parents[2]
target = work.parent / 'figures'
summary = json.loads((repo / 'evidence' / 'adversary_20261121' / 'summary.json').read_text(encoding='utf-8'))

ink, mid, light, grid, pale = '#253442', '#526473', '#98A7B2', '#E0E7EB', '#F1F5F6'
blue, rust, teal, gold = '#246A9B', '#AD523A', '#28776D', '#BE8B35'
for p in [Path(r'C:\Windows\Fonts\msyh.ttc'), Path(r'C:\Windows\Fonts\msyhbd.ttc')]:
    if p.exists():
        fm.fontManager.addfont(p)
plt.rcParams.update({
    'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
    'font.size': 9, 'text.color': ink, 'axes.labelcolor': ink,
    'axes.edgecolor': mid, 'axes.linewidth': 0.55, 'axes.titlesize': 10.0,
    'axes.titleweight': 'bold', 'xtick.color': mid, 'ytick.color': mid,
    'xtick.labelsize': 8.2, 'ytick.labelsize': 8.2,
    'grid.color': grid, 'grid.linewidth': 0.55, 'axes.axisbelow': True,
    'legend.frameon': False, 'legend.fontsize': 7.8,
    'pdf.fonttype': 42, 'ps.fonttype': 42, 'axes.unicode_minus': False,
})


def chart(ax, title='', x='', y='', gridaxis='y'):
    ax.spines[['top', 'right']].set_visible(False)
    ax.tick_params(length=2.8, pad=3)
    if gridaxis != 'none':
        ax.grid(axis=gridaxis)
    if title:
        ax.set_title(title, loc='left', pad=8)
    if x:
        ax.set_xlabel(x)
    if y:
        ax.set_ylabel(y)


def save(fig, index):
    fig.savefig(target / f'fig{index:02}.pdf', bbox_inches='tight', pad_inches=.085)
    preview = os.environ.get('FIG_PREVIEW_DIR')
    if preview:
        fig.savefig(Path(preview) / f'fig{index:02}.png', dpi=140, bbox_inches='tight', pad_inches=.085)
    plt.close(fig)


def fig17():
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.3, 3.15), layout='constrained',
                               gridspec_kw={'width_ratios': [1, 1.15]})
    chart(a, '(a) 响应概率与刺激、阈值的关系', '累积刺激 s / s', '响应概率 p', 'both')
    s = np.linspace(0, 8, 200)
    for theta, ls, lab in [(1.0, ':', 'θ=1.0 s（余量耗尽）'), (4.4, '-', 'θ≈4.4 s（本试验）'),
                           (6.0, '--', 'θ=6.0 s（余量充足）')]:
        a.plot(s, s**2 / (s**2 + theta**2), ls, color=mid if theta != 4.4 else blue, lw=1.1, label=lab)
    seen = set()
    for key, mk in [('hoard_thresh_s0', 'o'), ('hoard_thresh_s2', 's')]:
        for e in summary[key]['adversary_log']['threshold_trace']:
            k = (e['stimulus'], e['respond'])
            a.plot(e['stimulus'], e['p'], mk, ms=5.2,
                   mfc=rust if e['respond'] else 'white', mec=rust if e['respond'] else ink, mew=.8, zorder=3)
    a.set(xlim=(0, 8), ylim=(0, 1.02))
    handles, labels = a.get_legend_handles_labels()
    handles += [Line2D([], [], marker='o', ls='', mfc='white', mec=ink, ms=5),
                Line2D([], [], marker='o', ls='', mfc=rust, mec=rust, ms=5)]
    labels += ['实测：未响应', '实测：发起挑战']
    a.legend(handles, labels, loc='lower right', fontsize=7.2)

    chart(b, '(b) 后车 B1 的逐秒评估与撤销时刻', '仿真时间 / s', '响应概率 p', 'both')
    runs = [('hoard_thresh_s0', '种子 0 / 1（轨迹相同）', blue, 'o'),
            ('hoard_thresh_s2', '种子 2', teal, 's'),
            ('combined_def', '双对抗双防卫（虚线）', gold, '^')]
    for key, lab, c, mk in runs:
        tr = summary[key]['adversary_log']['threshold_trace']
        t = [e['t_ms'] / 1000 for e in tr]
        p = [e['p'] for e in tr]
        b.step(t, p, where='post', color=c, lw=1.1, label=lab, ls='--' if key == 'combined_def' else '-', zorder=2 if key == 'combined_def' else 3)
        b.plot(t, p, mk, color=c, ms=4.2, mfc='white', mew=.8)
        rv = summary[key]['adversary_log']['revocations'][0]
        b.plot(rv['t_ms'] / 1000, tr[-1]['p'], mk, color=c, ms=6.5, mew=.8)
        if key == 'hoard_thresh_s2':
            b.annotate(f"{rv['t_ms']/1000:.3f} s 撤销", (rv['t_ms'] / 1000, tr[-1]['p']),
                       xytext=(-6, 6), textcoords='offset points', ha='right',
                       fontsize=7.2, color=c)
        else:
            b.annotate(f"{rv['t_ms']/1000:.3f} s 撤销", (rv['t_ms'] / 1000, tr[-1]['p']),
                       xytext=(6, -2 if key != 'combined_def' else -10), textcoords='offset points',
                       fontsize=7.2, color=c)
    b.set(xlim=(80.0, 88.5), ylim=(0, .55))
    b.legend(loc='upper left', fontsize=7.2)
    save(fig, 17)


def fig18():
    order = [('regress_normal', '基线回归'), ('hoard_off', '虚占·无防卫'),
             ('hoard_thresh_s0', '虚占·阈值 s0'), ('hoard_thresh_s1', '虚占·阈值 s1'),
             ('hoard_thresh_s2', '虚占·阈值 s2'), ('spoof_off', '欺骗·无防卫'),
             ('spoof_auth', '欺骗·认证'), ('combined_def', '双对抗·双防卫')]
    tasks = [('red2', 'R2 交付（限 100 s）', rust, 'v', 100),
             ('blue1', 'B1 交付（限 350 s）', blue, 'o', 350),
             ('red1', 'R1 交付（限 250 s）', rust, '^', 250),
             ('blue2', 'B2 交付（限 350 s）', blue, 's', 350)]
    fig, ax = plt.subplots(figsize=(7.3, 3.55), layout='constrained')
    chart(ax, '', '仿真时间 / s', '', 'x')
    n = len(order)
    for i, (key, lab) in enumerate(order):
        y = n - 1 - i
        if i % 2 == 0:
            ax.axhspan(y - .5, y + .5, color=pale, zorder=0, lw=0)
        r = summary[key]
        for tk, tl, c, mk, dl in tasks:
            t = r['key_tasks_ms'][tk] / 1000
            late = t > dl
            ax.plot(t, y, mk, color=c, ms=6.0, mfc=c if tk.startswith('red') else 'white',
                    mec=c, mew=1.0, zorder=3)
            if late:
                ax.plot(t, y, 'x', color=ink, ms=9.5, mew=1.1, zorder=4)
        ax.text(402, y, f"{r['on_time']}/{r['total']}", va='center', ha='left', fontsize=8.0,
                weight='bold', color=rust if r['on_time'] < r['total'] else ink)
        log = r.get('adversary_log') or {}
        if log.get('revocations'):
            tv = log['revocations'][0]['t_ms'] / 1000
            ax.plot(tv, y, '|', color=teal, ms=11, mew=1.6, zorder=3)
        if log.get('forged_authorized'):
            ta = r['observation_authorized_ms'] / 1000
            ax.plot(ta, y + .28, 'D', color=gold, ms=5.0, zorder=3)
    for dl, txt in [(250, 'R1 期限'), (350, 'B1/B2 期限')]:
        ax.axvline(dl, color=mid, lw=.8, ls='--', zorder=1)
        ax.text(dl, n - .42, txt, ha='center', va='bottom', fontsize=7.4, color=mid,
                bbox=dict(facecolor='white', edgecolor='none', pad=1.2), zorder=2)
    ax.axvspan(80.1, 145, color='#F7EAE5', zorder=0, lw=0)
    ax.text(112.5, -0.95, '无防卫时 R1 虚占授权至 145 s', ha='center', va='bottom', fontsize=6.8, color=rust)
    ax.set_yticks(range(n))
    ax.set_yticklabels([lab for _, lab in order][::-1])
    ax.set(xlim=(60, 420), ylim=(-1.0, n - .1))
    ax.text(402, n - .42, '按期', ha='left', va='bottom', fontsize=7.4, color=mid)
    handles = [Line2D([], [], marker=mk, ls='', color=c, mfc=c if tk.startswith('red') else 'white', ms=6)
               for tk, tl, c, mk, dl in tasks]
    labels = [tl for tk, tl, c, mk, dl in tasks]
    handles += [Line2D([], [], marker='x', ls='', color=ink, ms=7),
                Line2D([], [], marker='|', ls='', color=teal, ms=9, mew=1.6),
                Line2D([], [], marker='D', ls='', color=gold, ms=5)]
    labels += ['超期', '阈值撤销红方授权', '伪造帧被采信']
    fig.legend(handles, labels, loc='outside lower center', ncol=4, fontsize=7.4)
    save(fig, 18)


if __name__ == '__main__':
    fig17()
    fig18()
    print('ok')

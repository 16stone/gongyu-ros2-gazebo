# -*- coding: utf-8 -*-
"""Figures 16 and 17 of the v11 report, drawn from referee truth.

Both read the committed evidence of f-webots-full-01, so the picture cannot drift
away from the numbers quoted in the text.
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(REPO, 'report_v11', 'figures')
RUN = os.path.join(REPO, 'evidence', 'webots', 'f-webots-full-01')
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'

INK = (28, 38, 52)
GRID = (226, 233, 240)
BLUE = (26, 92, 168)
RED = (186, 62, 52)
GOLD = (208, 158, 48)
GRAY = (120, 136, 152)
LIGHT = (232, 238, 245)


def f(sz, bold=False):
    path = FONT
    if bold:
        path = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
        if not os.path.exists(path):
            path = FONT
    return ImageFont.truetype(path, sz, index=2)


def load():
    rp = json.load(open(os.path.join(REPO, 'docs', 'demo', 'webots_replay_data.json'),
                        encoding='utf-8'))
    ev = [json.loads(l) for l in open(os.path.join(RUN, 'events.jsonl'), encoding='utf-8')]
    return rp, ev


def fig16(rp):
    W, H = 1600, 980
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    L, T, R, B = 92, 76, W - 40, H - 78

    xs = [r[1] for rows in rp['trajectories'].values() for r in rows]
    ys = [r[2] for rows in rp['trajectories'].values() for r in rows]
    x0, x1 = min(xs) - 1.0, max(xs) + 1.0
    y0, y1 = min(ys) - 1.0, max(ys) + 1.0
    sx = lambda v: L + (v - x0) / (x1 - x0) * (R - L)
    sy = lambda v: B - (v - y0) / (y1 - y0) * (B - T)

    d.text((L, 26), 'f-webots-full-01 八实体真值轨迹（裁判 getPosition，500 ms 采样）',
           font=f(30), fill=INK)

    for gx in range(int(x0), int(x1) + 1, 2):
        d.line([(sx(gx), T), (sx(gx), B)], fill=GRID, width=1)
        d.text((sx(gx) - 10, B + 10), str(gx), font=f(19), fill=GRAY)
    for gy in range(int(y0), int(y1) + 1, 2):
        d.line([(L, sy(gy)), (R, sy(gy))], fill=GRID, width=1)
        d.text((L - 42, sy(gy) - 10), str(gy), font=f(19), fill=GRAY)
    d.text(((L + R) / 2 - 30, B + 42), 'x / m', font=f(21), fill=INK)
    d.text((18, (T + B) / 2), 'y / m', font=f(21), fill=INK)

    # shared channel band
    d.rectangle([sx(2.05), sy(0.6), sx(4.95), sy(-0.6)], fill=(252, 243, 220),
                outline=GOLD, width=2)
    d.text((sx(2.05) + 8, sy(-0.6) + 8), '共享通道 2.05–4.95 m', font=f(20), fill=(158, 116, 30))

    for nid, (nx, ny) in rp['nodes'].items():
        if len(nid) > 2:
            continue
        d.rectangle([sx(nx) - 5, sy(ny) - 5, sx(nx) + 5, sy(ny) + 5],
                    fill=(255, 255, 255), outline=(150, 170, 190))
        tw = d.textlength(nid, font=f(19))
        d.rectangle([sx(nx) + 8, sy(ny) + 6, sx(nx) + 14 + tw, sy(ny) + 28],
                    fill=(255, 255, 255))
        d.text((sx(nx) + 10, sy(ny) + 7), nid, font=f(19), fill=(96, 120, 144))

    aerial = ('B3', 'R5')
    for nm, rows in rp['trajectories'].items():
        if not rows:
            continue
        pts = [(sx(r[1]), sy(r[2])) for r in rows]
        if nm in aerial:
            col, wd, dash = (108, 96, 168), 3, True
        elif nm.startswith('B'):
            col, wd, dash = BLUE, 4, False
        else:
            col, wd, dash = RED, 4, False
        if dash:
            for i in range(0, len(pts) - 1, 2):
                d.line([pts[i], pts[i + 1]], fill=col, width=wd)
        else:
            d.line(pts, fill=col, width=wd)
        for p in pts[::4]:
            d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=col)
        lx, ly = pts[-1]
        d.text((lx + 10, ly - 12), nm, font=f(21), fill=col)

    # legend
    lgd = [(BLUE, False, '蓝方地面'), (RED, False, '红方地面'), ((108, 96, 168), True, '无人机')]
    cx = L
    for col, dash, lab in lgd:
        yy = B + 62
        if dash:
            for i in range(0, 34, 6):
                d.line([(cx + i, yy), (cx + i + 3, yy)], fill=col, width=4)
        else:
            d.line([(cx, yy), (cx + 34, yy)], fill=col, width=4)
        d.text((cx + 44, yy - 12), lab, font=f(20), fill=INK)
        cx += 44 + len(lab) * 22 + 34

    im.save(os.path.join(OUT, 'fig16_webots_traj.png'))


def fig17(ev):
    res, ent, clr = {}, {}, {}
    for e in ev:
        k, a, pl = e['kind'], e['actor'], e['payload']
        if k == 'reservation_granted':
            res.setdefault(a, []).append((pl['start'], pl['end']))
        elif k == 'channel_enter':
            ent.setdefault(a, []).append(e['t_ms'])
        elif k == 'channel_cleared':
            clr.setdefault(a, []).append(e['t_ms'])

    rows = []
    for a in sorted(ent):
        for i, t0 in enumerate(ent[a]):
            t1 = clr[a][i]
            nom = res[a][i][1] if len(res.get(a, [])) > i else t1
            rows.append((a, t0, t1, nom))
    rows.sort(key=lambda r: r[1])
    seen = {}
    labelled = []
    for a, t0, t1, nom in rows:
        seen[a] = seen.get(a, 0) + 1
        total = sum(1 for r in rows if r[0] == a)
        labelled.append(('%s-%d' % (a, seen[a]) if total > 1 else a, t0, t1, nom))
    rows = labelled

    W, H = 1600, 620
    im = Image.new('RGB', (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    L, T, R, B = 150, 96, W - 60, H - 96
    tmax = max(r[3] for r in rows) / 1000.0 + 2
    sx = lambda ms: L + (ms / 1000.0) / tmax * (R - L)

    d.text((L, 30), '通道占用与提前释放：实心为实际占用，浅色为按名义预约本应继续占用',
           font=f(28), fill=INK)

    for g in range(0, int(tmax) + 1, 10):
        d.line([(sx(g * 1000), T), (sx(g * 1000), B)], fill=GRID, width=1)
        d.text((sx(g * 1000) - 12, B + 12), str(g), font=f(19), fill=GRAY)
    d.text(((L + R) / 2 - 40, B + 46), '仿真时间 / s', font=f(21), fill=INK)

    rowh = (B - T) / len(rows)
    for i, (a, t0, t1, nom) in enumerate(rows):
        cy = T + rowh * (i + 0.5)
        h = rowh * 0.46
        d.text((26, cy - 13), a, font=f(22), fill=INK)
        d.rectangle([sx(t0), cy - h, sx(t1), cy + h], fill=BLUE)
        d.rectangle([sx(t1), cy - h, sx(nom), cy + h], fill=LIGHT, outline=(198, 210, 224))
        d.text((sx(t1) + 6, cy - 12), '%.3f s 清' % (t1 / 1000.0), font=f(18), fill=BLUE)
        d.text((sx(t1) + 210, cy - 12), '提前 %.3f s' % ((nom - t1) / 1000.0),
               font=f(18), fill=(150, 110, 30))

    im.save(os.path.join(OUT, 'fig17_webots_channel.png'))
    for r in rows:
        print('%-3s enter %7.3f clear %7.3f nominal %7.3f early %6.3f'
              % (r[0], r[1] / 1000, r[2] / 1000, r[3] / 1000, (r[3] - r[2]) / 1000))


if __name__ == '__main__':
    rp, ev = load()
    fig16(rp)
    fig17(ev)
    print('figures written to', OUT)

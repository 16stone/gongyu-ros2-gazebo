#!/usr/bin/env python3
"""Render the main round into a same-source MP4.

Input is docs/demo/webots_replay_data.json, which is rebuilt from the raw telemetry and
referee events of f-webots-full-01.  Every drawn position, event and counter therefore
traces back to that run; nothing is re-simulated or hand-animated.
"""
import json, math, os, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'demo')
DATA = os.path.join(BASE, 'webots_replay_data.json')
OUT = os.path.join(BASE, 'webots_full_run.mp4')
FONT_CJK = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
FONT_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

W, H = 1200, 1080
HDR, FTR = 100, 88
FPS = 25

C_BG = (6, 9, 17)
C_PANEL = (13, 21, 34)
C_EDGE = (30, 45, 68)
C_GRID = (20, 32, 51)
C_GRID2 = (28, 46, 72)
C_TXT = (230, 238, 252)
C_MUT = (125, 142, 168)
C_ACC = (86, 212, 192)
C_GOLD = (242, 193, 78)
C_BLUE = (74, 168, 255)
C_RED = (255, 88, 104)

F = {}
def font(sz, mono=False):
    k = (sz, mono)
    if k not in F:
        F[k] = ImageFont.truetype(FONT_MONO if mono else FONT_CJK, sz)
    return F[k]

D = json.load(open(DATA, encoding='utf-8'))
TRAJ = D['trajectories']
EVENTS = D['events']
NODES = D['nodes']
MET = D['metrics']

# ---- geometry ---------------------------------------------------------------
YS = (-14.2, 9.8)
XS = (-0.7, 14.8)
BODY_T, BODY_B = HDR + 10, H - FTR - 10
S = (BODY_B - BODY_T) / (YS[1] - YS[0])
AW = (XS[1] - XS[0]) * S
AX0 = 300 + (1200 - 300 - 288 - AW) / 2 - 0  # centre inside 300..912
AX0 = 300
AY0 = BODY_T

def M(x, y):
    return (AX0 + (x - XS[0]) * S, AY0 + (y - YS[0]) * S)

CH_X = (1.8, 5.4)
CH_Y = 0.5

# pre-rendered glow sprites
def glow(color, r=26):
    im = Image.new('RGBA', (r * 2, r * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i in range(r, 0, -1):
        a = int(70 * (1 - i / r) ** 2)
        d.ellipse([r - i, r - i, r + i, r + i], fill=color + (a,))
    return im

G_BLUE = glow(C_BLUE)
G_RED = glow(C_RED)

def lerp(a, b, t):
    return a + (b - a) * t

def sample(rows, t):
    """position + heading at time t, linearly interpolated"""
    if not rows:
        return None
    if t <= rows[0][0]:
        return rows[0][1], rows[0][2], rows[0][3]
    if t >= rows[-1][0]:
        return rows[-1][1], rows[-1][2], rows[-1][3]
    lo, hi = 0, len(rows) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if rows[mid][0] <= t:
            lo = mid
        else:
            hi = mid
    a, b = rows[lo], rows[hi]
    u = (t - a[0]) / max(1.0, (b[0] - a[0]))
    return lerp(a[1], b[1], u), lerp(a[2], b[2], u), lerp(a[3], b[3], u)

def rr(d, box, rad, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=rad, fill=fill, outline=outline, width=width)

CHAPTERS = [
    (0, 6000, '一 · 出发与双扫描覆盖'),
    (6000, 16000, '二 · 进入共享通道'),
    (16000, 26000, '三 · 交会与让行'),
    (26000, 34000, '四 · 作业与观测上报'),
    (34000, 10 ** 9, '五 · 交付与清空'),
]

def chapter(t):
    for a, b, s in CHAPTERS:
        if a <= t < b:
            return s
    return ''

T_END = max(r[-1][0] for r in TRAJ.values())
TEAM = {n: (C_BLUE if n.startswith('B') else C_RED) for n in TRAJ}

def actor_status(nm, pos, events_by_actor, t):
    last = None
    for e in events_by_actor.get(nm, []):
        if e['t'] <= t:
            last = e
        else:
            break
    if last is None:
        return '待命'
    k = last['kind']
    return {
        'move_commanded': '前往 %s' % ((last.get('payload') or {}).get('node') or ''),
        'arrived': '到达',
        'channel_enter': '通道内',
        'channel_cleared': '已清空',
        'reservation_granted': '已授权',
        'inspection_report_created': '采样上报',
        'report_delivery': '报告送达',
        'dynamic_replan': '改派',
        'dispatch_held': '等待放行',
        'channel_release_recomputed': '释放重算',
        'task_completed': '任务完成',
    }.get(k, '运行中')

ev_by_actor = {}
for e in EVENTS:
    if e['actor']:
        ev_by_actor.setdefault(e['actor'], []).append(e)

def draw_frame(t):
    im = Image.new('RGB', (W, H), C_BG)
    d = ImageDraw.Draw(im)

    # panels
    rr(d, [16, HDR + 10, 288, H - FTR - 10], 14, C_PANEL, C_EDGE)
    rr(d, [916, HDR + 10, W - 16, H - FTR - 10], 14, C_PANEL, C_EDGE)

    # ---- arena ----
    rr(d, [AX0 - 10, AY0 - 10, AX0 + AW + 10, AY0 + (YS[1] - YS[0]) * S + 10], 12,
       (9, 15, 26), C_EDGE)
    for gx in range(0, 17):
        p1 = M(gx, YS[0]); p2 = M(gx, YS[1])
        d.line([p1, p2], fill=C_GRID2 if gx % 5 == 0 else C_GRID, width=1)
    for gy in range(-15, 11):
        p1 = M(XS[0], gy); p2 = M(XS[1], gy)
        d.line([p1, p2], fill=C_GRID2 if gy % 5 == 0 else C_GRID, width=1)

    # corridor
    x0, y0 = M(CH_X[0], -CH_Y); x1, y1 = M(CH_X[1], CH_Y)
    busy = False
    for nm, rows in TRAJ.items():
        p = sample(rows, t)
        if p and CH_X[0] - 0.05 <= p[0] <= CH_X[1] + 0.05 and abs(p[1]) < CH_Y + 0.12:
            busy = True
    d.rounded_rectangle([x0, y0, x1, y1], radius=4,
                        fill=(242, 193, 78, 0) if False else ((46, 37, 16) if not busy else (72, 54, 18)),
                        outline=C_GOLD, width=2)
    d.text((x0 + 6, y0 - 26), '共享通道  x∈[1.8,5.4]  y=±0.5', font=font(15), fill=C_GOLD)

    # nodes
    for nm, xy in NODES.items():
        px, py = M(xy[0], xy[1])
        d.ellipse([px - 3, py - 3, px + 3, py + 3], fill=(58, 84, 116))
        d.text((px + 5, py - 15), nm, font=font(12), fill=(72, 92, 118))

    # trails (8 s)
    for nm, rows in TRAJ.items():
        col = TEAM[nm]
        pts = [r for r in rows if t - 8000 <= r[0] <= t]
        if len(pts) > 1:
            for i in range(1, len(pts)):
                a = int(20 + 150 * i / len(pts))
                p1 = M(pts[i - 1][1], pts[i - 1][2]); p2 = M(pts[i][1], pts[i][2])
                d.line([p1, p2], fill=col + (a,), width=2)

    # actors
    for nm, rows in TRAJ.items():
        p = sample(rows, t)
        if not p:
            continue
        x, y, th = p
        px, py = M(x, y)
        g = G_BLUE if nm.startswith('B') else G_RED
        im.paste(g, (int(px) - 26, int(py) - 26), g)
        r = 7
        d.ellipse([px - r, py - r, px + r, py + r], fill=TEAM[nm], outline=(255, 255, 255), width=1)
        d.line([px, py, px + 15 * math.cos(th), py + 15 * math.sin(th)], fill=(255, 255, 255), width=2)
        d.text((px + 11, py + 6), nm, font=font(14), fill=C_TXT)

    # ---- header ----
    d.text((24, 20), '共域 · 八实体协同作业', font=font(28), fill=C_TXT)
    d.text((24, 58), 'Webots R2025a  ·  amax CPU  ·  run f-webots-full-01  ·  同源回放（裁判事件 + 遥测）',
           font=font(14), fill=C_MUT)
    d.text((W - 24, 24), chapter(t), font=font(20), fill=C_GOLD, anchor='ra')
    d.text((W - 24, 56), 'T+ %05.1f s' % (t / 1000.0), font=font(16, True), fill=C_ACC, anchor='ra')

    # ---- left panel: roster ----
    d.text((34, HDR + 24), '编队状态', font=font(17), fill=C_ACC)
    d.line([34, HDR + 50, 270, HDR + 50], fill=C_EDGE)
    yy = HDR + 62
    for nm in sorted(TRAJ):
        p = sample(TRAJ[nm], t)
        st = actor_status(nm, p, ev_by_actor, t)
        d.ellipse([36, yy + 5, 46, yy + 15], fill=TEAM[nm])
        d.text((54, yy), nm, font=font(15), fill=C_TXT)
        d.text((92, yy + 2), st[:6], font=font(13), fill=C_MUT)
        if p:
            d.text((270, yy + 2), '%5.1f,%5.1f' % (p[0], p[1]), font=font(12, True),
                   fill=(70, 88, 112), anchor='ra')
        yy += 26
    d.line([34, yy + 4, 270, yy + 4], fill=C_EDGE)
    yy += 16
    d.text((34, yy), '图例', font=font(15), fill=C_ACC); yy += 24
    d.ellipse([36, yy + 4, 46, yy + 14], fill=C_BLUE)
    d.text((54, yy), '蓝方 B1 B2 B3', font=font(13), fill=C_MUT); yy += 20
    d.ellipse([36, yy + 4, 46, yy + 14], fill=C_RED)
    d.text((54, yy), '红方 R1 R2 R3 R4 R5', font=font(13), fill=C_MUT)

    # ---- right panel: KPIs + event ticker ----
    d.text((932, HDR + 24), '本回合指标', font=font(17), fill=C_ACC)
    d.line([932, HDR + 50, W - 32, HDR + 50], fill=C_EDGE)
    done = sum(1 for e in EVENTS
               if e['kind'] == 'arrived' and e['t'] <= t and e.get('task'))
    kpis = [('按期完成', '%d / %d' % (done, MET['total'])),
            ('通道违例', str(MET['violation_count'])),
            ('进入 / 释放', '%d / %d' % (MET['channel_enters'], MET['channel_releases'])),
            ('报告接受', str(MET['accepted_reports']))]
    yy = HDR + 64
    for k, v in kpis:
        d.text((932, yy), k, font=font(14), fill=C_MUT)
        d.text((W - 32, yy - 6), v, font=font(22, True), fill=C_TXT, anchor='ra')
        yy += 44
    d.line([932, yy, W - 32, yy], fill=C_EDGE); yy += 14
    d.text((932, yy), '事件流', font=font(16), fill=C_ACC); yy += 26
    recent = [e for e in EVENTS if e['t'] <= t][-9:]
    for e in reversed(recent):
        lbl = {'channel_enter': '进入通道', 'channel_cleared': '清空通道',
               'reservation_granted': '授权', 'arrived': '到达',
               'move_commanded': '派单', 'report_delivery': '报告送达',
               'inspection_report_created': '采样', 'dynamic_replan': '改派',
               'dispatch_held': '等待放行', 'opportunity_cost_evaluation': '机会成本',
               'task_completed': '任务完成', 'channel_release_recomputed': '释放重算'}.get(e['kind'], e['kind'])
        nd = (e.get('payload') or {}).get('node') or ''
        d.text((932, yy), '%6.1fs' % (e['t'] / 1000.0), font=font(12, True), fill=(70, 88, 112))
        d.text((984, yy), '%s' % (e['actor'] or '--'), font=font(12, True), fill=(90, 112, 142))
        d.text((1024, yy), lbl, font=font(12), fill=C_MUT)
        if nd and len(nd) <= 3:
            d.text((W - 32, yy), nd, font=font(12, True), fill=(90, 112, 142), anchor='ra')
        yy += 19
        if yy > H - FTR - 30:
            break

    if t >= T_END - 60:
        bx, by = AX0 + AW / 2, AY0 + (YS[1] - YS[0]) * S / 2 + 40
        rr(d, [bx - 190, by - 46, bx + 190, by + 46], 12, (10, 18, 30), C_ACC, 2)
        d.text((bx, by - 30), '本回合闭合', font=font(19), fill=C_ACC, anchor='ma')
        d.text((bx, by - 2), '%d / %d 按期     %d 违例' % (MET['on_time'], MET['total'],
               MET['violation_count']), font=font(21), fill=C_TXT, anchor='ma')

    # ---- footer timeline ----
    tx0, tx1 = 24, W - 24
    ty = H - FTR + 26
    d.rounded_rectangle([tx0, ty, tx1, ty + 8], radius=4, fill=(22, 33, 50))
    for e in EVENTS:
        ex = tx0 + (tx1 - tx0) * (e['t'] / T_END)
        col = C_GOLD if e['kind'] in ('channel_enter', 'channel_cleared') else (44, 66, 94)
        d.line([ex, ty - 5, ex, ty + 13], fill=col, width=1)
    px = tx0 + (tx1 - tx0) * min(1.0, t / T_END)
    d.rounded_rectangle([tx0, ty, px, ty + 8], radius=4, fill=C_ACC)
    d.ellipse([px - 6, ty - 2, px + 6, ty + 10], fill=(255, 255, 255))
    d.text((tx0, ty + 16), '0 s', font=font(11, True), fill=C_MUT)
    d.text((tx1, ty + 16), '%.0f s' % (T_END / 1000.0), font=font(11, True), fill=C_MUT, anchor='ra')
    d.text(((tx0 + tx1) / 2, ty + 16), '%s  ·  共 %d 条裁判事件，全部可回溯到 evidence/webots/f-webots-full-01'
           % (D['run'], len(EVENTS)), font=font(11), fill=C_MUT, anchor='ma')
    return im

def main():
    frames = int((T_END / 1000.0 + 3.0) * FPS) + 1
    cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', '%dx%d' % (W, H), '-r', str(FPS), '-i', '-',
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
           '-pix_fmt', 'yuv420p', '-movflags', '+faststart', OUT]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(frames):
        t = min(T_END, int(i * 1000 / FPS))
        pr.stdin.write(draw_frame(t).tobytes())
        if i % 100 == 0:
            print('frame %d/%d' % (i, frames), flush=True)
    pr.stdin.close()
    pr.wait()
    print('WROTE', OUT, os.path.getsize(OUT), 'bytes', frames, 'frames')

main()

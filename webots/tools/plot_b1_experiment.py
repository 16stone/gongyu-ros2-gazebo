#!/usr/bin/env python3
"""Plot plan/track overlays, localization errors, and the two-plane installation."""
import argparse
import csv
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from b1_experiment import CARD


class Figure:
    colors = ("#006a95", "#b74a24")

    def __init__(self, title, width=1000, height=540):
        self.width, self.height = width, height
        self.items = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
                      '<rect width="100%" height="100%" fill="white"/>',
                      '<g font-family="Noto Sans CJK SC, Droid Sans Fallback, DejaVu Sans" fill="#18304b">']
        self.text(52, 42, title, 24)

    def text(self, x, y, label, size=16, anchor="start", color="#18304b"):
        self.items.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" text-anchor="{anchor}">{escape(label)}</text>')

    def box(self, x, y, w, h, color, stroke="none"):
        self.items.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}" stroke="{stroke}"/>')

    def line(self, points, color="#c8d1db", width=1, dash=""):
        coords = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        self.items.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>')

    def mark(self, x, y, color="#18304b"):
        self.items.append(f'<circle cx="{x}" cy="{y}" r="4.4" fill="{color}"/>')

    def write(self, path):
        path.write_text("\n".join(self.items + ["</g></svg>"]) + "\n", encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text())


def plot_track(layout, result, runs, out):
    fig = Figure("B1 全局栅格路径与电机驱动真值轨迹", height=590)
    unit = 109.0
    ox, oy = 103, 283
    point = lambda x, y: (ox + unit * x, oy - unit * y)
    for x in range(8):
        fig.line([point(x, -1.7), point(x, 1.6)])
        fig.text(point(x, 0)[0], 502, str(x), anchor="middle")
    for y in (-1, 0, 1):
        fig.line([point(-0.4, y), point(7.3, y)])
        fig.text(47, point(0, y)[1]+5, str(y), anchor="end")
    fig.text(51, 100, "y / m", 15)
    fig.text(930, 502, "x / m", 15)
    for _, x0, x1, y0, y1, _ in CARD["layouts"][layout]:
        px, py = point(x0, y1)
        fig.box(px, py, (x1-x0)*unit, (y1-y0)*unit, "#e5eaf0", "#8295a8")
    for i, algorithm in enumerate(("dijkstra", "astar")):
        selection = next((r for r in result["runs"] if r["layout"] == layout and r["algorithm"] == algorithm), None)
        if selection is None:
            continue
        root = runs / selection["id"]
        plan = read_json(root / "result/plan.json")
        trace = [json.loads(line)["position"][:2] for line in (root / "bus/truth_B1.jsonl").read_text().splitlines()]
        fig.line([point(*p) for p in plan["path"]], fig.colors[i], 1.6, "8 5")
        fig.line([point(*p) for p in trace[::3]], fig.colors[i], 2.6)
        fig.line([(115 + 328*i, 542), (147 + 328*i, 542)], fig.colors[i], 2.6)
        fig.text(157 + 328*i, 548, f"{algorithm} · 真值 {selection['actual_path_m']:.2f} m", color=fig.colors[i])
    for p, name, shift in ((CARD["start"][:2], "起点", -16), (CARD["goal"], "目标", 25)):
        x, y = point(*p)
        fig.mark(x, y)
        fig.text(x, y+shift, name, 15, anchor="middle")
    fig.text(760, 547, "虚线表示栅格路径", 15)
    fig.write(out / f"b1_track_{layout}.svg")


def plot_localization(source, path):
    with source.open() as file:
        rows = list(csv.DictReader(file))
    t_max = float(rows[-1]["t_ms"]) / 1000
    fig = Figure("同一电机回合的轮式定位与扫描地图校正", height=685)
    for i, (prefix, unit) in enumerate((("xy", "平面误差 / m"), ("yaw", "航向误差 / °"))):
        keys = (f"odom_{prefix}_err_{'m' if i == 0 else 'deg'}", f"fused_{prefix}_err_{'m' if i == 0 else 'deg'}")
        max_y = max(float(row[key]) for key in keys for row in rows) * 1.08
        max_y = max(max_y, 1e-5)
        top = 100 + i*280
        bottom = top + 196
        def point(t, value):
            return 115 + 790*t/t_max, bottom - 195*value/max_y
        for j in range(5):
            xs, ys = point(0, max_y*j/4)
            fig.line([(xs, ys), (905, ys)])
            fig.text(102, ys+4, f"{max_y*j/4:.2f}", 14, anchor="end")
        for j in range(6):
            x = point(t_max*j/5, 0)[0]
            fig.line([(x, top), (x, bottom)])
            fig.text(x, bottom+22, f"{t_max*j/5:.1f}", 14, anchor="middle")
        for key, color in zip(keys, fig.colors):
            fig.line([point(float(row["t_ms"])/1000, float(row[key])) for row in rows], color, 2.5)
        fig.text(52, top-15, unit, 16)
        fig.text(905, bottom+42, "仿真时间 / s", 14, anchor="end")
    for i, label in enumerate(("车轮编码器", "车轮编码器 + 主雷达地图校正")):
        x = 150 + 340*i
        fig.line([(x, 652), (x+36, 652)], fig.colors[i], 2.5)
        fig.text(x+45, 658, label, color=fig.colors[i])
    fig.write(path)


def plot_installation(path):
    fig = Figure("B1 前置双平面 LiDAR 安装与低箱几何", height=550)
    fig.text(58, 84, "俯视 · 平面相对位置", 18)
    fig.text(515, 84, "侧视 · 名义距地高度", 18)
    ox, oy, scale = 240, 302, 435
    fig.box(ox-0.20*scale, oy-0.17*scale, 0.40*scale, 0.34*scale, "#dce9f0", "#57768a")
    for sy in (-0.17, 0.17):
        px, py = ox-38, oy-sy*scale-11
        fig.box(px, py, 76, 22, "#394f64")
    fig.line([(ox+36, oy-0.17*scale), (ox+36, oy+0.17*scale)], "#bd502c", 2, "4 3")
    fig.text(ox-30, oy+105, "轮距 0.34 m", 15)
    fig.mark(ox+0.24*scale, oy, "#006a95")
    fig.line([(ox+0.24*scale, oy), (ox+0.43*scale, oy)], "#006a95", 2.5)
    fig.text(ox+0.15*scale, oy-28, "双雷达", 15)
    fig.text(ox+0.44*scale, oy+6, "+x", 15)
    fig.text(ox+0.054*scale, oy-92, "+y", 15)
    x, floor = 590, 455
    fig.line([(510, floor), (930, floor)], "#455d76", 2)
    fig.box(x-0.20*scale, floor-0.19*scale, 0.40*scale, 0.14*scale, "#dce9f0", "#57768a")
    fig.box(824, floor-0.27*scale, 73, 0.27*scale, "#e9a955", "#9f5d25")
    fig.text(860, floor-56, "低箱", 15, anchor="middle")
    for mode, height, color in (("主雷达", 0.320, fig.colors[0]), ("低位雷达", 0.225, fig.colors[1])):
        sx, sy = x+0.24*scale, floor-height*scale
        fig.mark(sx, sy, color)
        fig.line([(sx, sy), (920, sy)], color, 2.3, "8 5")
        fig.text(520, sy-8, f"{mode} {height:.3f} m", 15, color=color)
    fig.text(825, floor-0.27*scale-7, "箱顶 0.270 m", 14)
    fig.text(58, 515, "地面视图与车体示意，横向障碍距离按布局设置。", 15)
    fig.write(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("analysis", type=Path)
    parser.add_argument("runs", type=Path)
    args = parser.parse_args()
    result = read_json(args.analysis / "summary.json")
    plot_installation(args.analysis / "b1_lidar_installation.svg")
    for layout in ("open", "narrow"):
        if any(r["layout"] == layout for r in result["runs"]):
            plot_track(layout, result, args.runs, args.analysis)
    localization = sorted(args.analysis.glob("loc_*narrow-astar*.csv"))
    if localization:
        plot_localization(localization[0], args.analysis / "b1_localization.svg")


if __name__ == "__main__":
    main()

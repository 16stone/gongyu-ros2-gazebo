#!/usr/bin/env python3
"""Generate a low-box experiment without changing the frozen eight-entity world."""
from pathlib import Path

from generate_world import pbr, pos, shape_box, solid

root = Path(__file__).resolve().parents[1] / "worlds"
source = (root / "web_medium_phys.wbt").read_text(encoding="utf-8")
prefix, b1 = source.split("DEF B1 Robot", 1)
b1, suffix = b1.split("DEF B2 Robot", 1)
low = 'Lidar { name "lidar_low" translation 0.18 0 0.18 horizontalResolution'
replacement = 'Lidar { name "lidar_low" translation 0.24 0 0.105 projection "cylindrical" horizontalResolution'
assert b1.count(low) == 1
size = (0.20, 0.18, 0.27)
box = solid("course_low_box", pos(7.25, 2.23, size[2] / 2),
            shape_box(size, pbr((0.90, 0.64, 0.11))), bounding="Box { size 0.20 0.18 0.27 }")
world = prefix + "DEF COURSE_LOW_BOX " + box + "\nDEF B1 Robot" + b1.replace(low, replacement) + "DEF B2 Robot" + suffix
(root / "web_medium_phys_lowbox.wbt").write_text(world, encoding="utf-8", newline="\n")

"""Composes the A3 blueprint poster (SVG, mm units) from the hidden-line views in views.json."""

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent / "vendor/SO-ARM100/Simulation/SO101"

SHEET_W, SHEET_H = 420.0, 297.0
FRAME = 10.0

BLUE = "#164a8c"
BLUE_DEEP = "#0c2d5e"
INK = "#eef5ff"
INK_SOFT = "#a9c3ea"

TITLE_FONT = "DIN Condensed"
LABEL_FONT = "Avenir Next Condensed"
MONO_FONT = "PT Mono"

JOINTS = [
    ("shoulder_pan", "ROTATION BASE", "1/191"),
    ("shoulder_lift", "ÉPAULE", "1/345"),
    ("elbow_flex", "COUDE", "1/191"),
    ("wrist_flex", "FLEXION POIGNET", "1/147"),
    ("wrist_roll", "ROTATION POIGNET", "1/147"),
    ("gripper", "PINCE / GÂCHETTE", "1/147"),
]


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


class View:
    """Places a rendered view on the sheet: model (u, v) in mm -> sheet (x, y) in mm."""

    def __init__(self, data, scale, anchor_x, anchor_y, align="bottom-center"):
        self.data = data
        self.scale = scale
        points = [p for ring in data["fill"] for p in ring]
        self.u_min = min(p[0] for p in points)
        self.u_max = max(p[0] for p in points)
        self.v_min = min(p[1] for p in points)
        self.v_max = max(p[1] for p in points)
        width = (self.u_max - self.u_min) * scale
        height = (self.v_max - self.v_min) * scale
        if align == "bottom-center":
            self.x0 = anchor_x - width / 2
            self.y0 = anchor_y
        else:
            self.x0 = anchor_x
            self.y0 = anchor_y
        self.width, self.height = width, height

    def point(self, u, v):
        return (self.x0 + (u - self.u_min) * self.scale, self.y0 - (v - self.v_min) * self.scale)

    def joint(self, name):
        return self.point(*self.data["joints_2d"][name])

    def path(self, polylines, close=False):
        parts = []
        for line in polylines:
            coords = [self.point(u, v) for u, v in line]
            parts.append("M" + " L".join(f"{fmt(x)} {fmt(y)}" for x, y in coords) + ("Z" if close else ""))
        return " ".join(parts)

    def svg(self, widths, hidden_opacity):
        lines = self.data["lines"]
        outline_w, silhouette_w, crease_w, hidden_w = widths
        return "\n".join([
            f'<path d="{self.path(self.data["fill"], close=True)}" fill="{INK}" fill-opacity="0.07" fill-rule="evenodd" stroke="none"/>',
            f'<path d="{self.path(lines["hidden"])}" stroke="{INK_SOFT}" stroke-width="{hidden_w}" stroke-opacity="{hidden_opacity}" fill="none"/>',
            f'<path d="{self.path(lines["crease"])}" stroke="{INK}" stroke-width="{crease_w}" stroke-opacity="0.9" fill="none"/>',
            f'<path d="{self.path(lines["silhouette"])}" stroke="{INK}" stroke-width="{silhouette_w}" fill="none"/>',
            f'<path d="{self.path(lines["outline"])}" stroke="{INK}" stroke-width="{outline_w}" fill="none"/>',
        ])


def text(x, y, content, size, font=LABEL_FONT, weight=500, anchor="start", fill=INK, spacing=0.0, opacity=1.0):
    return (
        f'<text x="{fmt(x)}" y="{fmt(y)}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
        f'text-anchor="{anchor}" fill="{fill}" fill-opacity="{opacity}" letter-spacing="{spacing}">{content}</text>'
    )


def line(x1, y1, x2, y2, width=0.2, color=INK, opacity=1.0, dash=None):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" stroke="{color}" '
        f'stroke-width="{width}" stroke-opacity="{opacity}"{dash_attr}/>'
    )


def arrow_head(x, y, angle, size=1.6):
    left = (x - size * math.cos(angle - 0.3), y - size * math.sin(angle - 0.3))
    right = (x - size * math.cos(angle + 0.3), y - size * math.sin(angle + 0.3))
    return f'<path d="M{fmt(x)} {fmt(y)} L{fmt(left[0])} {fmt(left[1])} L{fmt(right[0])} {fmt(right[1])}Z" fill="{INK}"/>'


def aligned_dimension(p1, p2, offset, label, size=2.3):
    """Dimension line parallel to p1-p2, pushed `offset` mm to the left of the p1->p2 direction."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    nx, ny = dy / length, -dx / length
    a = (p1[0] + nx * offset, p1[1] + ny * offset)
    b = (p2[0] + nx * offset, p2[1] + ny * offset)
    extension = 1.5 if offset > 0 else -1.5
    angle = math.atan2(dy, dx)
    text_angle = math.degrees(angle)
    if text_angle > 90 or text_angle < -90:
        text_angle += 180
    mid = ((a[0] + b[0]) / 2 + nx * 1.4 * (1 if offset > 0 else -1), (a[1] + b[1]) / 2 + ny * 1.4 * (1 if offset > 0 else -1))
    return "\n".join([
        line(p1[0] + nx * 1.0, p1[1] + ny * 1.0, a[0] + nx * extension, a[1] + ny * extension, 0.12, opacity=0.8),
        line(p2[0] + nx * 1.0, p2[1] + ny * 1.0, b[0] + nx * extension, b[1] + ny * extension, 0.12, opacity=0.8),
        line(a[0], a[1], b[0], b[1], 0.15),
        arrow_head(a[0], a[1], angle + math.pi),
        arrow_head(b[0], b[1], angle),
        f'<g transform="translate({fmt(mid[0])} {fmt(mid[1])}) rotate({fmt(text_angle)})">'
        + text(0, 0.8, label, size, MONO_FONT, 400, "middle")
        + "</g>",
    ])


def balloon(joint_xy, offset, number, radius=3.0):
    x, y = joint_xy
    bx, by = x + offset[0], y + offset[1]
    distance = math.hypot(offset[0], offset[1])
    ex, ey = bx - offset[0] / distance * radius, by - offset[1] / distance * radius
    return "\n".join([
        f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="0.7" fill="{INK}"/>',
        line(x, y, ex, ey, 0.15),
        f'<circle cx="{fmt(bx)}" cy="{fmt(by)}" r="{radius}" fill="{BLUE}" stroke="{INK}" stroke-width="0.3"/>',
        text(bx, by + 1.35, str(number), 3.8, TITLE_FONT, 700, "middle"),
    ])


def joint_limits(urdf_name):
    root = ET.parse(SIM_DIR / urdf_name).getroot()
    limits = {}
    for joint in root.findall("joint"):
        limit = joint.find("limit")
        if joint.get("type") == "revolute" and limit is not None:
            limits[joint.get("name")] = (math.degrees(float(limit.get("lower"))), math.degrees(float(limit.get("upper"))))
    return limits


def range_label(lower, upper):
    if abs(lower + upper) < 0.6:
        return f"± {upper:.0f}°"
    return f"{lower:+.0f}° / {upper:+.0f}°"


def background():
    grid = []
    for i in range(0, int(SHEET_W) + 1, 5):
        major = i % 25 == 0
        grid.append(line(i, 0, i, SHEET_H, 0.18 if major else 0.08, INK, 0.16 if major else 0.07))
    for j in range(0, int(SHEET_H) + 1, 5):
        major = j % 25 == 0
        grid.append(line(0, j, SHEET_W, j, 0.18 if major else 0.08, INK, 0.16 if major else 0.07))
    return f"""
<defs>
  <radialGradient id="paper" cx="50%" cy="45%" r="75%">
    <stop offset="0%" stop-color="{BLUE}"/>
    <stop offset="70%" stop-color="#123f7a"/>
    <stop offset="100%" stop-color="{BLUE_DEEP}"/>
  </radialGradient>
  <filter id="grain" x="0" y="0" width="100%" height="100%">
    <feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="7"/>
    <feColorMatrix values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.09 0"/>
  </filter>
</defs>
<rect width="{SHEET_W}" height="{SHEET_H}" fill="url(#paper)"/>
<rect width="{SHEET_W}" height="{SHEET_H}" filter="url(#grain)"/>
<g>{''.join(grid)}</g>"""


def frame():
    inner = FRAME
    parts = [
        f'<rect x="{inner}" y="{inner}" width="{SHEET_W - 2 * inner}" height="{SHEET_H - 2 * inner}" fill="none" stroke="{INK}" stroke-width="0.7"/>',
        f'<rect x="{inner - 4}" y="{inner - 4}" width="{SHEET_W - 2 * inner + 8}" height="{SHEET_H - 2 * inner + 8}" fill="none" stroke="{INK}" stroke-width="0.2" stroke-opacity="0.7"/>',
    ]
    columns = 8
    column_w = (SHEET_W - 2 * inner) / columns
    for i in range(columns):
        cx = inner + column_w * (i + 0.5)
        for y in (inner - 1.3, SHEET_H - inner + 3.2):
            parts.append(text(cx, y, str(i + 1), 2.6, MONO_FONT, 400, "middle", INK, opacity=0.75))
        if i:
            x = inner + column_w * i
            parts.append(line(x, inner - 4, x, inner, 0.2, opacity=0.7))
            parts.append(line(x, SHEET_H - inner, x, SHEET_H - inner + 4, 0.2, opacity=0.7))
    rows = 6
    row_h = (SHEET_H - 2 * inner) / rows
    for j in range(rows):
        cy = inner + row_h * (j + 0.5) + 0.9
        for x in (inner - 2, SHEET_W - inner + 2):
            parts.append(text(x, cy, "ABCDEF"[j], 2.6, MONO_FONT, 400, "middle", INK, opacity=0.75))
        if j:
            y = inner + row_h * j
            parts.append(line(inner - 4, y, inner, y, 0.2, opacity=0.7))
            parts.append(line(SHEET_W - inner, y, SHEET_W - inner + 4, y, 0.2, opacity=0.7))
    for x, y in ((SHEET_W / 2, inner - 4), (SHEET_W / 2, SHEET_H - inner + 4)):
        parts.append(line(x, y - 3, x, y + 3, 0.35))
    return "\n".join(parts)


def header():
    x, y = 18, 18
    return "\n".join([
        text(x, y + 20.5, "SO-101", 27, TITLE_FONT, 700, spacing=0.4),
        line(x + 63, y + 3, x + 63, y + 21, 0.3),
        text(x + 67, y + 8.5, "BRAS ROBOTIQUE 6 AXES", 6.2, LABEL_FONT, 600, spacing=0.5),
        text(x + 67, y + 15.2, "PAIRE LEADER / FOLLOWER · TÉLÉOPÉRATION", 4.2, LABEL_FONT, 500, spacing=0.35, opacity=0.9),
        text(x + 67, y + 20.5, "PLAN D'ENSEMBLE RELEVÉ SUR LE MODÈLE CAO OFFICIEL (URDF + STL)", 2.7, MONO_FONT, 400, opacity=0.7),
    ])


def specs_block():
    x, y = 300, 21
    rows = [
        ("DEGRÉS DE LIBERTÉ", "5 + PINCE"),
        ("ACTIONNEURS", "12 × FEETECH STS3215"),
        ("BUS", "SÉRIE TTL · ID 1 → 6"),
        ("PIÈCES", "IMPRESSION 3D · PLA"),
    ]
    parts = []
    for i, (key, value) in enumerate(rows):
        yy = y + i * 5.4
        parts.append(text(x, yy, key, 2.5, MONO_FONT, 400, opacity=0.7))
        parts.append(text(402, yy, value, 3.3, LABEL_FONT, 600, "end", spacing=0.2))
        parts.append(line(x, yy + 1.6, 402, yy + 1.6, 0.1, opacity=0.35))
    return "\n".join(parts)


def hero_caption(cx, y, letter, name, subtitle):
    return "\n".join([
        f'<circle cx="{fmt(cx - 27)}" cy="{fmt(y - 2.4)}" r="4.2" fill="none" stroke="{INK}" stroke-width="0.35"/>',
        text(cx - 27, y - 0.3, letter, 6, TITLE_FONT, 700, "middle"),
        text(cx - 20, y, name, 9, TITLE_FONT, 700, spacing=0.8),
        line(cx - 20, y + 2.2, cx + 34, y + 2.2, 0.25),
        text(cx - 20, y + 6, subtitle, 2.7, MONO_FONT, 400, opacity=0.8),
    ])


def teleop_link(x_from, x_to, y):
    path_d = f"M{fmt(x_from)} {fmt(y)} C{fmt(x_from - 8)} {fmt(y - 14)} {fmt(x_to + 8)} {fmt(y - 14)} {fmt(x_to)} {fmt(y)}"
    return "\n".join([
        f'<path d="{path_d}" fill="none" stroke="{INK}" stroke-width="0.3" stroke-dasharray="1.6 1.2"/>',
        arrow_head(x_to, y, math.radians(115), 2.0),
        text((x_from + x_to) / 2, y - 17.5, "TÉLÉOPÉRATION", 3.1, LABEL_FONT, 600, "middle", spacing=0.6),
        text((x_from + x_to) / 2, y - 13.8, "LEADER → FOLLOWER", 2.4, MONO_FONT, 400, "middle", opacity=0.75),
    ])


def scale_bar(x, y, scale, label, model_length=100):
    """Alternating black/white scale bar of `model_length` model mm."""
    parts = []
    step = 10 * scale
    for i in range(int(model_length / 10)):
        fill = INK if i % 2 == 0 else "none"
        parts.append(f'<rect x="{fmt(x + i * step)}" y="{y}" width="{fmt(step)}" height="1.4" fill="{fill}" stroke="{INK}" stroke-width="0.15"/>')
    for value in (0, model_length // 2, model_length):
        parts.append(text(x + value * scale, y + 4.2, str(value), 2.0, MONO_FONT, 400, "middle"))
    parts.append(text(x + model_length * scale / 2, y - 1.6, label + " · mm", 2.2, MONO_FONT, 400, "middle", opacity=0.8))
    return "\n".join(parts)


def side_elevation(view, title, dimension_side):
    parts = [view.svg((0.3, 0.16, 0.1, 0.06), 0.3)]
    shoulder, elbow, wrist = view.joint("shoulder_lift"), view.joint("elbow_flex"), view.joint("wrist_flex")
    model = view.data["joints_2d"]
    upper_len = math.dist(model["shoulder_lift"], model["elbow_flex"])
    fore_len = math.dist(model["elbow_flex"], model["wrist_flex"])
    parts.append(aligned_dimension(shoulder, elbow, 7 * dimension_side, f"{upper_len:.1f}", 2.2))
    parts.append(aligned_dimension(elbow, wrist, 7 * dimension_side, f"{fore_len:.1f}", 2.2))
    for x, y in (shoulder, elbow, wrist):
        parts.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="1.1" fill="none" stroke="{INK}" stroke-width="0.15"/>')
        parts.append(line(x - 2.2, y, x + 2.2, y, 0.1, opacity=0.8))
        parts.append(line(x, y - 2.2, x, y + 2.2, 0.1, opacity=0.8))

    height_mm = view.v_max - view.v_min
    length_mm = view.u_max - view.u_min
    left, right = view.x0, view.x0 + view.width
    top, bottom = view.y0 - view.height, view.y0
    x_dim = left - 5 if dimension_side > 0 else right + 5
    parts.append(line(x_dim - 1.5, top, x_dim + 1.5, top, 0.12))
    parts.append(line(x_dim - 1.5, bottom, x_dim + 1.5, bottom, 0.12))
    parts.append(line(x_dim, top, x_dim, bottom, 0.15))
    parts.append(arrow_head(x_dim, top, -math.pi / 2))
    parts.append(arrow_head(x_dim, bottom, math.pi / 2))
    parts.append(
        f'<g transform="translate({fmt(x_dim - 1.2)} {fmt((top + bottom) / 2)}) rotate(-90)">'
        + text(0, 0, f"{height_mm:.0f}", 2.2, MONO_FONT, 400, "middle") + "</g>"
    )
    y_dim = bottom + 5
    parts.append(line(left, bottom + 1, left, y_dim + 1.5, 0.12))
    parts.append(line(right, bottom + 1, right, y_dim + 1.5, 0.12))
    parts.append(line(left, y_dim, right, y_dim, 0.15))
    parts.append(arrow_head(left, y_dim, math.pi))
    parts.append(arrow_head(right, y_dim, 0))
    parts.append(text((left + right) / 2, y_dim - 1.0, f"{length_mm:.0f}", 2.2, MONO_FONT, 400, "middle"))
    parts.append(line(left - 3, bottom, right + 3, bottom, 0.2, opacity=0.6, dash="3 1 0.6 1"))
    return "\n".join(parts)


def joint_table(x, y, width, follower_limits, leader_limits):
    columns = [("N°", 0), ("ARTICULATION", 7), ("AMPLITUDE", 36), ("FOLLOWER", 61), ("LEADER", 82.5)]
    row_h = 6.2
    parts = [text(x, y - 4, "TABLEAU DES ARTICULATIONS", 3.6, LABEL_FONT, 600, spacing=0.4)]
    parts.append(f'<rect x="{x}" y="{y - 1}" width="{width}" height="{row_h * 7 + 1}" fill="none" stroke="{INK}" stroke-width="0.3"/>')
    for label, dx in columns:
        parts.append(text(x + dx + 1.5, y + 3.3, label, 2.3, MONO_FONT, 400, opacity=0.75))
    parts.append(line(x, y + row_h - 0.5, x + width, y + row_h - 0.5, 0.25))
    for i, (name, label, leader_ratio) in enumerate(JOINTS):
        yy = y + row_h * (i + 1)
        lower, upper = follower_limits[name]
        amplitude = range_label(lower, upper)
        if name == "gripper":
            leader_lower, leader_upper = leader_limits[name]
            amplitude = f"{lower:+.0f}/{upper:+.0f}° · {leader_lower:.0f}/{leader_upper:.0f}°"
        parts.append(text(x + 3.5, yy + 4.2, str(i + 1), 3.6, TITLE_FONT, 700, "middle"))
        parts.append(text(x + 8.5, yy + 4.0, label, 2.9, LABEL_FONT, 600, spacing=0.15))
        parts.append(text(x + 37.5, yy + 4.0, amplitude, 2.0 if name == "gripper" else 2.5, MONO_FONT, 400))
        parts.append(text(x + 62.5, yy + 4.0, "STS3215 1/345", 2.2, MONO_FONT, 400))
        parts.append(text(x + 84.0, yy + 4.0, f"STS3215 {leader_ratio}", 2.2, MONO_FONT, 400))
        if i < 5:
            parts.append(line(x, yy + row_h - 0.5, x + width, yy + row_h - 0.5, 0.1, opacity=0.5))
    for _, dx in columns[1:]:
        parts.append(line(x + dx, y - 1, x + dx, y + row_h * 7, 0.12, opacity=0.6))
    parts.append(text(x, y + row_h * 7 + 4, "AMPLITUDES : LIMITES URDF, PINCE FOLLOWER · GÂCHETTE LEADER · RAPPORTS : DOC. LEROBOT", 1.8, MONO_FONT, 400, opacity=0.65))
    return "\n".join(parts)


def title_block(x, y, width, height):
    cells = [
        (0, 0, 1.0, 13, "DÉSIGNATION", "SO-101 · LEADER / FOLLOWER", 4.6),
        (0, 13, 1.0, 9, "CONCEPTION · SOURCE CAO", "THEROBOTSTUDIO × HUGGING FACE · SO-ARM100", 2.7),
        (0, 22, 0.25, 9, "FORMAT", "A3", 3.6),
        (0.25, 22, 0.25, 9, "UNITÉS", "mm", 3.6),
        (0.5, 22, 0.25, 9, "ÉCHELLES", "1:2 · 1:5", 3.2),
        (0.75, 22, 0.25, 9, "FEUILLE", "1 / 1", 3.6),
        (0, 31, 0.5, 9, "DATE", "27.10.2026", 3.4),
        (0.5, 31, 0.5, 9, "PROPRIÉTAIRE", "ALEXANDRE", 3.4),
    ]
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{BLUE_DEEP}" fill-opacity="0.35" stroke="{INK}" stroke-width="0.5"/>']
    for fx, fy, fw, fh, key, value, size in cells:
        cx, cy, cw = x + fx * width, y + fy, fw * width
        parts.append(f'<rect x="{fmt(cx)}" y="{fmt(cy)}" width="{fmt(cw)}" height="{fh}" fill="none" stroke="{INK}" stroke-width="0.18"/>')
        parts.append(text(cx + 1.4, cy + 2.6, key, 1.8, MONO_FONT, 400, opacity=0.7))
        parts.append(text(cx + 1.4, cy + fh - 2.2, value, size, LABEL_FONT if size < 4 else TITLE_FONT, 600 if size < 4 else 700, spacing=0.2))
    return "\n".join(parts)


def main(views_path, output_path):
    data = json.loads(Path(views_path).read_text())
    follower_limits = joint_limits("so101_new_calib.urdf")
    leader_limits = joint_limits("so101_leader_new_calib.urdf")

    follower_hero = View(data["follower"]["views"]["hero"], 0.5, 108, 182)
    leader_hero = View(data["leader"]["views"]["hero"], 0.5, 316, 182)
    follower_side = View(data["follower_ref"]["views"]["side"], 0.2, 68, 272)
    leader_side = View(data["leader_ref"]["views"]["side"], 0.2, 166, 272)

    follower_balloons = {
        "shoulder_pan": (-14, 6), "shoulder_lift": (-15, -4), "elbow_flex": (-8, -11),
        "wrist_flex": (4, -14), "wrist_roll": (14, -10), "gripper": (12, -8),
    }
    leader_balloons = {
        "shoulder_pan": (14, 6), "shoulder_lift": (15, -4), "elbow_flex": (8, -11),
        "wrist_flex": (-4, -14), "wrist_roll": (-14, -10), "gripper": (-12, -8),
    }

    body = [
        background(),
        frame(),
        header(),
        specs_block(),
        line(18, 50, 402, 50, 0.25, opacity=0.6),
        follower_hero.svg((0.42, 0.22, 0.14, 0.07), 0.32),
        leader_hero.svg((0.42, 0.22, 0.14, 0.07), 0.32),
    ]
    for (name, _, _), number in zip(JOINTS, range(1, 7)):
        body.append(balloon(follower_hero.joint(name), follower_balloons[name], number))
        body.append(balloon(leader_hero.joint(name), leader_balloons[name], number))
    body += [
        hero_caption(80, 192, "A", "FOLLOWER", "6 × STS3215 1/345 · PINCE À MORS MOBILE · ÉCH. 1:2"),
        hero_caption(296, 192, "B", "LEADER", "STS3215 1/191 · 1/345 · 1/147 · POIGNÉE + GÂCHETTE · ÉCH. 1:2"),
        teleop_link(252, 168, 88),
        line(18, 202, 402, 202, 0.25, opacity=0.6),
        text(18, 207.5, "ÉLÉVATIONS EN POSITION DE CALIBRATION (MI-COURSE) · ÉCH. 1:5 · COTES ENTRE AXES", 3.0, LABEL_FONT, 600, spacing=0.4),
        scale_bar(185, 176, 0.5, "ÉCH. 1:2"),
        side_elevation(follower_side, "A", 1),
        side_elevation(leader_side, "B", -1),
        text(follower_side.x0 + follower_side.width / 2, 284, "A · FOLLOWER", 2.8, LABEL_FONT, 600, "middle", spacing=0.4),
        text(leader_side.x0 + leader_side.width / 2, 284, "B · LEADER", 2.8, LABEL_FONT, 600, "middle", spacing=0.4),
        joint_table(224, 220, 102, follower_limits, leader_limits),
        title_block(332, 240, 70, 40),
    ]

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W}mm" height="{SHEET_H}mm" '
        f'viewBox="0 0 {SHEET_W} {SHEET_H}" stroke-linecap="round" stroke-linejoin="round">\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )
    Path(output_path).write_text(svg)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

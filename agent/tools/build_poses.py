"""원형 도달쑤에서 팔만 바꾼 포즈 그림을 만든다. 실행: python tools/build_poses.py (agent 폴더에서)

얼굴·머리·몸통·다리·꼬리는 원형 픽셀을 그대로 쓰고, 바꿀 쪽 팔만 지운 뒤
원형과 같은 노랑·검정 외곽선으로 새 팔을 그린다. 결과는 poses/ 에 저장된다.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent.parent
BASE = HERE.parent / "images" / "dodalssu-basic.png"
OUT = HERE / "poses"

YELLOW = (253, 195, 58, 255)
BLACK = (1, 1, 1, 255)
LINE = 19          # 원형 외곽선 굵기(px)
ARM = 72           # 팔 굵기(외곽선 제외)
SS = 4             # 팔을 매끄럽게 그리기 위한 확대 배율

# 머리 아래쪽 외곽선이 끝나는 y (x별 실측값). 이 위는 머리라서 절대 건드리지 않는다.
HEAD_BOTTOM = [(165, 500), (186, 600), (217, 650), (260, 697), (290, 725), (320, 748), (350, 767),
               (410, 794), (470, 812), (560, 822), (650, 812), (710, 795), (770, 766), (800, 746),
               (830, 721), (860, 692), (896, 650), (925, 600), (955, 500)]

# 팔을 지운 뒤 새로 그을 몸통 옆선(외곽선 가운데 기준)
TORSO_EDGE = {
    "left": [(398, 780), (362, 880), (336, 980), (325, 1050), (322, 1078)],
    "right": [(720, 780), (755, 880), (776, 980), (781, 1050), (781, 1078)],
}
# 원형 팔 안쪽 선(몸통 위에 그려진 선). 팔을 지울 때 노랑으로 덮는다.
INNER_ARM_LINE = {"left": ((397, 865), (340, 1022)), "right": ((720, 868), (780, 1022))}

# 포즈: 바꿀 팔 → 어깨·팔꿈치·손 좌표. hands는 소품을 놓을 손 위치.
POSES = {
    "basic": {"arms": {}, "hands": {"left": (300, 1000), "right": (820, 1000)}},
    "hold_right": {
        "arms": {"right": [(690, 790), (850, 1000), (700, 925)]},
        "hands": {"left": (300, 1000), "right": (700, 925)},
    },
    "hold_both": {
        "arms": {"left": [(430, 790), (280, 1010), (505, 960)], "right": [(690, 790), (840, 1010), (615, 960)]},
        "hands": {"both": (560, 960)},
    },
    "wave_right": {
        "arms": {"right": [(700, 790), (930, 880), (905, 690)]},
        "hands": {"left": (300, 1000)},
    },
}


def _interp(points, v, axis_in=0):
    """points 를 따라 선형 보간. axis_in=0 이면 x→y, 1 이면 y→x."""
    pts = sorted(points, key=lambda p: p[axis_in])
    out = 1 - axis_in
    if v <= pts[0][axis_in]:
        return pts[0][out]
    for a, b in zip(pts, pts[1:]):
        if a[axis_in] <= v <= b[axis_in]:
            t = (v - a[axis_in]) / (b[axis_in] - a[axis_in])
            return a[out] + t * (b[out] - a[out])
    return pts[-1][out]


def head_bottom(x: float) -> float:
    return _interp(HEAD_BOTTOM, x, 0)


def _dist_to_segment(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def remove_arm(im: Image.Image, side: str) -> None:
    px = im.load()
    edge = TORSO_EDGE[side]
    y0, y1 = edge[0][1], edge[-1][1]
    for y in range(int(y0) - 40, int(y1) + 1):
        ex = _interp(edge, min(max(y, y0), y1), 1)
        xs = range(100, int(ex)) if side == "left" else range(int(ex) + 1, im.width - 100)
        for x in xs:
            if y > head_bottom(x) + 1:
                px[x, y] = (0, 0, 0, 0)
    # 몸통 위에 남은 원형 팔 안쪽 선을 노랑으로 덮는다
    a, b = INNER_ARM_LINE[side]
    for y in range(min(a[1], b[1]) - 20, max(a[1], b[1]) + 20):
        for x in range(min(a[0], b[0]) - 25, max(a[0], b[0]) + 25):
            p = px[x, y]
            if p[3] and y > head_bottom(x) + 1 and _dist_to_segment((x, y), a, b) < 17 and sum(p[:3]) < 690:
                px[x, y] = YELLOW
    # 새 몸통 옆선
    d = ImageDraw.Draw(im)
    d.line(edge, fill=BLACK, width=LINE, joint="curve")
    for p in (edge[0], edge[-1]):
        d.ellipse([p[0] - LINE / 2, p[1] - LINE / 2, p[0] + LINE / 2, p[1] + LINE / 2], fill=BLACK)


def _curve(pts, steps: int = 40):
    """어깨·팔꿈치·손 세 점을 부드러운 곡선(2차 베지어)으로 잇는다."""
    (x0, y0), (cx, cy), (x1, y1) = pts
    return [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1,
             (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1)
            for t in (i / steps for i in range(steps + 1))]


def draw_arm(layer: ImageDraw.ImageDraw, pts) -> None:
    s = [(x * SS, y * SS) for x, y in _curve(pts)]
    for color, w in ((BLACK, (ARM + 2 * LINE) * SS), (YELLOW, ARM * SS)):
        layer.line(s, fill=color, width=w, joint="curve")
        for x, y in s:
            r = w / 2
            layer.ellipse([x - r, y - r, x + r, y + r], fill=color)


def head_layer(base: Image.Image) -> Image.Image:
    """원형에서 머리만 남긴 그림. 합성할 때 맨 위에 다시 얹어 머리가 가려지지 않게 한다."""
    head = base.copy()
    hp = head.load()
    for x in range(base.width):
        hb = head_bottom(x)
        for y in range(int(hb) + 2, base.height):
            hp[x, y] = (0, 0, 0, 0)
    return head


def build(pose: dict, base: Image.Image, head: Image.Image) -> tuple[Image.Image, Image.Image]:
    """(새 팔을 뺀 몸, 새 팔) 두 장을 돌려준다. 손에 든 소품은 이 둘 사이에 끼운다."""
    body = base.copy()
    for side in pose["arms"]:
        remove_arm(body, side)
    body.alpha_composite(head)
    big = Image.new("RGBA", (base.width * SS, base.height * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    for pts in pose["arms"].values():
        draw_arm(d, pts)
    arms = big.resize(base.size, Image.LANCZOS)
    return body, arms


def main() -> None:
    base = Image.open(BASE).convert("RGBA")
    OUT.mkdir(exist_ok=True)
    head = head_layer(base)
    head.save(OUT / "head.png")
    for name, pose in POSES.items():
        body, arms = build(pose, base, head)
        body.save(OUT / f"{name}_body.png")
        arms.save(OUT / f"{name}_arms.png")
        preview = body.copy()
        preview.alpha_composite(arms)
        preview.alpha_composite(head)
        preview.save(OUT / f"{name}.png")
        print("saved", name)


if __name__ == "__main__":
    main()

"""입력 글 → Gemini(무료 글 모델)가 관광지·포즈·소품을 고름 → 미리 만든 그림들을 합성.

얼굴·머리·몸·다리는 원형 도달쑤 픽셀 그대로이고, 포즈는 팔만 바꾼 그림(poses/)을 쓴다.
겹치는 순서: 배경 → 몸 → 팔 → 머리 → 머리·목 장식 → 손에 든 소품 → 바닥 소품.
앞에 놓이는 소품은 얼굴 영역을 마스크로 비워 얼굴을 덮지 못하게 한다.
"""

import base64
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from prompts import (BLOCKED_ELEMENTS, CANVAS_H, CANVAS_W, DEFAULT_SPOT, FACE_GUARD, FIXED_SLOTS, POSES, PROPS,
                     SLOT_KINDS, planner_instruction)

HERE = Path(__file__).resolve().parent
POSE_DIR = HERE / "poses"
BG_DIR = HERE / "assets" / "backgrounds"
PROP_DIR = HERE / "assets" / "props"
OUTPUT_DIR = HERE / "outputs"
BASE_IMAGE = HERE.parent / "images" / "dodalssu-basic.png"
# 같은 관광지에 사진(AI 이미지)과 일러스트가 둘 다 있으면 사진을 먼저 쓴다
BG_EXTS = [".png", ".jpg", ".jpeg", ".webp", ".svg"]
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml"}


def _models(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, default).split(",") if m.strip()]


# 앞의 모델이 붐비거나 한도를 넘으면 다음 모델을 쓴다
TEXT_MODELS = _models("GEMINI_MODELS", "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview")
MAX_TRIES = int(os.getenv("MAX_TRIES", "3"))

SVG_NS = "http://www.w3.org/2000/svg"
ALLOWED_TAGS = {"g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
ALLOWED_ATTRS = {
    "d", "x", "y", "width", "height", "cx", "cy", "r", "rx", "ry", "x1", "y1", "x2", "y2", "points",
    "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-dasharray",
    "opacity", "fill-opacity", "stroke-opacity", "fill-rule", "transform",
}


class AgentError(Exception):
    pass


class BusyError(AgentError):
    """모델이 붐비거나 한도를 넘은 경우. 다시 시도해도 같으니 바로 알린다."""


def _gemini() -> genai.Client:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise AgentError("GEMINI_API_KEY가 설정되지 않았어요. agent/.env 파일을 확인해 주세요.")
    return genai.Client(api_key=key)


def _call(client: genai.Client, models: list[str], contents: list, config: types.GenerateContentConfig):
    last_error = None
    for model in models:
        try:
            return client.models.generate_content(model=model, contents=contents, config=config)
        except genai_errors.APIError as e:
            if e.code not in (429, 503):
                raise
            last_error = e
    raise BusyError(f"Gemini 모델이 모두 붐비거나 한도를 넘었어요. 잠시 뒤 다시 시도해 주세요. ({last_error})")


def background_file(spot: str) -> Path | None:
    for ext in BG_EXTS:
        p = BG_DIR / f"{spot}{ext}"
        if p.exists():
            return p
    return None


def spots_with_background() -> list[str]:
    return sorted({p.stem for p in BG_DIR.glob("*") if p.suffix.lower() in BG_EXTS})


def plan_scene(client: genai.Client, user_text: str) -> dict:
    config = types.GenerateContentConfig(
        system_instruction=planner_instruction(spots_with_background()),
        response_mime_type="application/json",
    )
    resp = _call(client, TEXT_MODELS, [user_text], config)
    try:
        return json.loads(resp.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise AgentError("Gemini 응답을 읽지 못했어요.") from e


def sanitize_svg(fragment: str) -> str:
    """허용한 도형 태그와 속성만 남긴다. 스크립트·이미지·링크·글자는 모두 버린다."""
    try:
        root = ET.fromstring(f'<g xmlns="{SVG_NS}">{fragment}</g>')
    except ET.ParseError as e:
        raise AgentError(f"SVG를 읽지 못했어요: {e}") from e

    def clean(el: ET.Element) -> ET.Element | None:
        tag = el.tag.split("}")[-1]
        if tag not in ALLOWED_TAGS:
            return None
        out = ET.Element(tag)
        for k, v in el.attrib.items():
            k = k.split("}")[-1]
            if k in ALLOWED_ATTRS and "url(" not in v and "javascript" not in v.lower():
                out.set(k, v)
        for child in el:
            c = clean(child)
            if c is not None:
                out.append(c)
        return out

    shapes = [c for c in (clean(ch) for ch in root) if c is not None]
    if not shapes:
        raise AgentError("SVG에 그릴 도형이 없어요.")
    return "".join(ET.tostring(s, encoding="unicode") for s in shapes)


def _data_uri(path: Path) -> str:
    return f"data:{MIME[path.suffix.lower()]};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _full_image(path: Path, fit: str = "none") -> str:
    return f'<image width="{CANVAS_W}" height="{CANVAS_H}" preserveAspectRatio="{fit}" href="{_data_uri(path)}"/>'


def _svg_size(path: Path) -> tuple[float, float]:
    m = re.search(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', path.read_text(encoding="utf-8"))
    return float(m.group(1)), float(m.group(2))


def _prop_image(name: str, x: float, y: float, align: tuple[float, float]) -> str:
    """소품을 (x, y) 에 둔다. align 은 그 점이 소품 상자 안 어디인지(가로, 세로 비율)."""
    prop = PROPS[name]
    path = PROP_DIR / prop["file"]
    vw, vh = _svg_size(path)
    w = prop["width"]
    h = w * vh / vw
    return (f'<image x="{x - w * align[0]:.1f}" y="{y - h * align[1]:.1f}" width="{w}" height="{h:.1f}" '
            f'href="{_data_uri(path)}"/>')


def place_items(pose: str, items: dict) -> tuple[dict[str, str], list[str]]:
    """Gemini가 고른 소품 중 자리와 종류가 맞는 것만 남긴다. (자리 → 소품, 쓰지 못한 소품)"""
    allowed_slots = set(POSES[pose]["hands"]) | set(FIXED_SLOTS)
    placed, dropped = {}, []
    for slot, name in (items or {}).items():
        if not name:
            continue
        if (slot in allowed_slots and name in PROPS and PROPS[name]["kind"] in SLOT_KINDS[slot]
                and not any(w in name for w in BLOCKED_ELEMENTS)):
            placed[slot] = name
        else:
            dropped.append(name)
    return placed, dropped


def compose(pose: str, placed: dict[str, str], background: str) -> str:
    hands = POSES[pose]["hands"]
    held = "".join(_prop_image(n, *hands[s], PROPS[n]["grip"]) for s, n in placed.items() if s in hands)
    align = {"bottom": (0.5, 1.0), "top": (0.5, 0.0)}
    worn = "".join(_prop_image(n, *FIXED_SLOTS[s][0], align[FIXED_SLOTS[s][1]])
                   for s, n in placed.items() if s in ("head", "neck"))
    ground = "".join(_prop_image(n, *FIXED_SLOTS[s][0], align[FIXED_SLOTS[s][1]])
                     for s, n in placed.items() if s.startswith("ground"))
    f = FACE_GUARD
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<defs><mask id="face-guard" maskUnits="userSpaceOnUse" x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#fff"/>'
        f'<ellipse cx="{f["cx"]}" cy="{f["cy"]}" rx="{f["rx"]}" ry="{f["ry"]}" fill="#000"/></mask></defs>'
        f'<g id="background">{background}</g>'
        f'{_full_image(POSE_DIR / f"{pose}_body.png")}'
        f'{_full_image(POSE_DIR / f"{pose}_arms.png")}'
        f'{_full_image(POSE_DIR / "head.png")}'
        f'<g mask="url(#face-guard)">{worn}{held}</g>'
        f"{ground}"
        "</svg>"
    )


def generate(user_text: str) -> dict:
    client = _gemini()
    last_error = None
    for _ in range(MAX_TRIES):
        try:
            plan = plan_scene(client, user_text)
            spot = plan.get("spot") or DEFAULT_SPOT
            pose = plan.get("pose") if plan.get("pose") in POSES else "basic"
            bg_path = background_file(spot)
            if bg_path:
                fit = "xMidYMid slice"
                background = _full_image(bg_path, fit)
            else:
                background = sanitize_svg(plan.get("back_svg", ""))
            break
        except BusyError:
            raise
        except AgentError as e:
            last_error = e
    else:
        raise AgentError(f"그림을 만들지 못했어요. 다시 시도해 주세요. ({last_error})")

    placed, dropped = place_items(pose, plan.get("items"))

    OUTPUT_DIR.mkdir(exist_ok=True)
    name = datetime.now().strftime("dodalssu_%Y%m%d_%H%M%S.svg")
    (OUTPUT_DIR / name).write_text(compose(pose, placed, background), encoding="utf-8")

    return {
        "image_url": f"/outputs/{name}",
        "spot": spot,
        "spot_known": plan.get("spot_known", True),
        "spot_drawn": bg_path is None,
        "pose": POSES[pose]["desc"],
        "scene_ko": plan.get("scene_ko", ""),
        "elements": list(placed.values()),
        "missing": plan.get("missing", []) + dropped,
        "removed": plan.get("removed", []),
    }

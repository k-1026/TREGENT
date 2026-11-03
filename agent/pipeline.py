"""입력 글 → Gemini(무료 글 모델)가 배경·소품 SVG를 그림 → 원형 그림 위아래로 합성.

원형 도달쑤 픽셀은 손대지 않고 그대로 넣으며, 앞 레이어는 얼굴 영역을 마스크로 비워
소품이 얼굴을 덮지 못하게 한다.
"""

import base64
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from prompts import CANVAS_H, CANVAS_W, FACE_GUARD, PLANNER_INSTRUCTION

HERE = Path(__file__).resolve().parent
BASE_IMAGE = HERE.parent / "images" / "dodalssu-basic.png"
OUTPUT_DIR = HERE / "outputs"


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


def plan_scene(client: genai.Client, user_text: str) -> dict:
    config = types.GenerateContentConfig(
        system_instruction=PLANNER_INSTRUCTION,
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


def compose(back: str, front: str) -> str:
    base64_png = base64.b64encode(BASE_IMAGE.read_bytes()).decode()
    f = FACE_GUARD
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<defs><mask id="face-guard" maskUnits="userSpaceOnUse" x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#fff"/>'
        f'<ellipse cx="{f["cx"]}" cy="{f["cy"]}" rx="{f["rx"]}" ry="{f["ry"]}" fill="#000"/></mask></defs>'
        f'<g id="background">{back}</g>'
        f'<image width="{CANVAS_W}" height="{CANVAS_H}" href="data:image/png;base64,{base64_png}"/>'
        f'<g id="props" mask="url(#face-guard)">{front}</g>'
        "</svg>"
    )


def generate(user_text: str) -> dict:
    client = _gemini()
    last_error = None
    for _ in range(MAX_TRIES):
        try:
            plan = plan_scene(client, user_text)
            back = sanitize_svg(plan.get("back_svg", ""))
            front = sanitize_svg(plan.get("front_svg", ""))
            break
        except BusyError:
            raise
        except AgentError as e:
            last_error = e
    else:
        raise AgentError(f"그림을 만들지 못했어요. 다시 시도해 주세요. ({last_error})")

    OUTPUT_DIR.mkdir(exist_ok=True)
    name = datetime.now().strftime("dodalssu_%Y%m%d_%H%M%S.svg")
    (OUTPUT_DIR / name).write_text(compose(back, front), encoding="utf-8")

    return {
        "image_url": f"/outputs/{name}",
        "scene_ko": plan.get("scene_ko", ""),
        "elements": plan.get("elements", []),
        "missing": [],
        "removed": plan.get("removed", []),
    }

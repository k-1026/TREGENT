"""입력 글 → Gemini(무료 글 모델)가 에셋과 자리를 고름 → 원형 그림과 에셋을 합성.

원형 도달쑤 픽셀은 손대지 않고 그대로 넣으며, 앞 레이어는 얼굴 영역을 마스크로 비워
소품이 얼굴을 덮지 못하게 한다.
"""

import base64
import io
import json
import os
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image

from prompts import BLOCKED_ELEMENTS, CANVAS_H, CANVAS_W, FACE_GUARD, FOLDER_DESC, SLOTS, planner_instruction

HERE = Path(__file__).resolve().parent
BASE_IMAGE = HERE.parent / "images" / "dodalssu-basic.png"
ASSETS_DIR = Path(os.getenv("ASSETS_DIR", HERE / "assets"))
OUTPUT_DIR = HERE / "outputs"
IMAGE_EXTS = {".png", ".webp", ".jpg", ".jpeg"}


def _models(name: str, default: str) -> list[str]:
    return [m.strip() for m in os.getenv(name, default).split(",") if m.strip()]


# 앞의 모델이 붐비거나 한도를 넘으면 다음 모델을 쓴다
TEXT_MODELS = _models("GEMINI_MODELS", "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview")

SVG_NS = "http://www.w3.org/2000/svg"
# 머리 장식과 바닥 소품은 상자 아래쪽에 붙이고, 나머지는 가운데에 둔다
BOTTOM_ALIGNED = {"head", "ground_left", "ground_right"}


class AgentError(Exception):
    pass


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
    raise AgentError(f"Gemini 모델이 모두 붐비거나 한도를 넘었어요. 잠시 뒤 다시 시도해 주세요. ({last_error})")


def _blocked(name: str) -> bool:
    return any(word in name for word in BLOCKED_ELEMENTS)


def list_assets() -> dict[str, dict[str, Path]]:
    """폴더 이름 → {에셋 이름: 파일 경로}. 파일 이름(확장자 제외)이 에셋 이름이다."""
    catalog = {}
    for folder in FOLDER_DESC:
        d = ASSETS_DIR / folder
        files = sorted(p for p in d.glob("*") if p.suffix.lower() in IMAGE_EXTS) if d.is_dir() else []
        catalog[folder] = {p.stem: p for p in files if not _blocked(p.stem)}
    return catalog


def _data_uri(path: Path, crop: bool) -> tuple[str, int, int]:
    """그림을 PNG data URI로 바꾼다. crop이면 투명한 여백을 잘라낸다."""
    im = Image.open(path).convert("RGBA")
    if crop:
        bbox = im.getchannel("A").getbbox()
        if bbox:
            im = im.crop(bbox)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), im.width, im.height


def plan_scene(client: genai.Client, user_text: str, catalog: dict[str, dict[str, Path]]) -> dict:
    names = {folder: list(items) for folder, items in catalog.items()}
    config = types.GenerateContentConfig(
        system_instruction=planner_instruction(names),
        response_mime_type="application/json",
    )
    resp = _call(client, TEXT_MODELS, [user_text], config)
    try:
        return json.loads(resp.text)
    except (TypeError, json.JSONDecodeError) as e:
        raise AgentError("Gemini 응답을 읽지 못했어요.") from e


def _placed_image(slot: str, path: Path) -> str:
    uri, _, _ = _data_uri(path, crop=True)
    cx, cy, w, h = SLOTS[slot]["box"]
    align = "xMidYMax" if slot in BOTTOM_ALIGNED else "xMidYMid"
    return (
        f'<image x="{cx - w / 2}" y="{cy - h / 2}" width="{w}" height="{h}" '
        f'preserveAspectRatio="{align} meet" href="{uri}"/>'
    )


def compose(background: Path | None, placed: dict[str, Path]) -> str:
    base_uri, _, _ = _data_uri(BASE_IMAGE, crop=False)
    f = FACE_GUARD
    back = "".join(_placed_image(s, p) for s, p in placed.items() if SLOTS[s]["layer"] == "back")
    front = "".join(_placed_image(s, p) for s, p in placed.items() if SLOTS[s]["layer"] == "front")
    bg = ""
    if background:
        bg_uri, _, _ = _data_uri(background, crop=False)
        bg = f'<image width="{CANVAS_W}" height="{CANVAS_H}" preserveAspectRatio="xMidYMid slice" href="{bg_uri}"/>'
    return (
        f'<svg xmlns="{SVG_NS}" viewBox="0 0 {CANVAS_W} {CANVAS_H}" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<defs><mask id="face-guard" maskUnits="userSpaceOnUse" x="0" y="0" width="{CANVAS_W}" height="{CANVAS_H}">'
        f'<rect width="{CANVAS_W}" height="{CANVAS_H}" fill="#fff"/>'
        f'<ellipse cx="{f["cx"]}" cy="{f["cy"]}" rx="{f["rx"]}" ry="{f["ry"]}" fill="#000"/></mask></defs>'
        f'<g id="background">{bg}</g>'
        f'<g id="behind">{back}</g>'
        f'<image width="{CANVAS_W}" height="{CANVAS_H}" href="{base_uri}"/>'
        f'<g id="props" mask="url(#face-guard)">{front}</g>'
        "</svg>"
    )


def generate(user_text: str) -> dict:
    catalog = list_assets()
    if not any(items for folder, items in catalog.items() if folder != "background"):
        raise AgentError("등록된 소품이 없어요. agent/assets 폴더에 소품 그림을 넣어 주세요.")

    plan = plan_scene(_gemini(), user_text, catalog)

    # Gemini가 고른 이름 중 실제로 있는 것만 쓴다
    background = catalog["background"].get(plan.get("background") or "")
    placed = {}
    for slot, name in (plan.get("slots") or {}).items():
        if slot in SLOTS and name in catalog[SLOTS[slot]["folder"]]:
            placed[slot] = catalog[SLOTS[slot]["folder"]][name]
    if not placed and not background:
        raise AgentError("어울리는 소품을 찾지 못했어요. 다른 표현으로 적거나 소품을 더 넣어 주세요.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    name = datetime.now().strftime("dodalssu_%Y%m%d_%H%M%S.svg")
    (OUTPUT_DIR / name).write_text(compose(background, placed), encoding="utf-8")

    return {
        "image_url": f"/outputs/{name}",
        "scene_ko": plan.get("scene_ko", ""),
        "elements": ([background.stem] if background else []) + [p.stem for p in placed.values()],
        "missing": plan.get("missing", []),
        "removed": plan.get("removed", []),
    }

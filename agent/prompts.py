"""도달쑤 에이전트가 쓰는 원형 좌표, 소품 자리, 서문시장 요소 사전, Gemini 지시문.

원형 그림(images/dodalssu-basic.png)은 픽셀 그대로 쓰고, 미리 그려 둔 소품·배경 에셋을
정해진 자리에 합성한다. Gemini는 어떤 에셋을 어느 자리에 둘지만 고른다.
"""

# 원형 이미지 크기(px). 이미지 배경은 투명하다.
CANVAS_W, CANVAS_H = 1145, 1374

# 앞 레이어가 덮을 수 없는 얼굴 영역(눈·코·수염·입). 마스크로 강제한다.
FACE_GUARD = {"cx": 560, "cy": 500, "rx": 255, "ry": 170}

# 소품을 놓는 자리. folder 의 그림을 box(중심 x, 중심 y, 가로, 세로) 안에 비율을 지켜 맞춘다.
# layer: back = 도달쑤 뒤, front = 도달쑤 앞
SLOTS = {
    "hand_left":    {"folder": "hand",   "box": (290, 960, 300, 300),  "layer": "front", "desc": "그림 기준 왼손에 든 것"},
    "hand_right":   {"folder": "hand",   "box": (830, 960, 300, 300),  "layer": "front", "desc": "그림 기준 오른손에 든 것"},
    "head":         {"folder": "head",   "box": (560, 190, 560, 300),  "layer": "front", "desc": "머리 위 모자·머리띠·장식"},
    "neck":         {"folder": "neck",   "box": (560, 830, 440, 200),  "layer": "front", "desc": "목도리·목걸이·스카프"},
    "body":         {"folder": "body",   "box": (560, 1030, 520, 460), "layer": "front", "desc": "앞치마·조끼처럼 몸 앞에 입는 옷"},
    "back":         {"folder": "back",   "box": (560, 900, 980, 900),  "layer": "back",  "desc": "망토·큰 원단처럼 등 뒤로 두르는 것"},
    "ground_left":  {"folder": "ground", "box": (170, 1200, 300, 300), "layer": "front", "desc": "왼발 옆 바닥에 놓인 것"},
    "ground_right": {"folder": "ground", "box": (975, 1200, 300, 300), "layer": "front", "desc": "오른발 옆 바닥에 놓인 것"},
}

FOLDER_DESC = {
    "background": "배경 (캔버스 전체)",
    "hand": "손에 드는 소품",
    "head": "머리에 쓰는 것",
    "neck": "목에 거는 것",
    "body": "몸 앞에 입는 옷",
    "back": "등 뒤로 두르는 것",
    "ground": "바닥에 놓는 것",
}

# 서문시장에서 즐길 거리. 공구 관련 요소는 넣지 않는다.
SEOMUN_MARKET_ELEMENTS = {
    "먹거리": ["칼국수", "납작만두", "씨앗호떡", "어묵", "떡볶이"],
    "야시장": ["줄지은 노점", "백열등과 조명", "꼬치 같은 길거리 음식"],
    "원단·포목": ["알록달록한 원단 두루마리", "한복 천", "재봉 소품"],
    "시장 풍경": ["상가 간판", "비닐 천막 지붕", "장바구니", "흥정하는 분위기"],
}

# 그림에 넣지 않는 요소. 사용자가 입력에 적어도 뺀다.
BLOCKED_ELEMENTS = ["공구", "공구골목", "렌치", "스패너", "볼트", "너트", "드라이버", "망치", "펜치", "톱"]


def _lines(d: dict) -> str:
    return "\n".join(f"- {k}: {', '.join(v) if isinstance(v, list) else v}" for k, v in d.items())


def planner_instruction(catalog: dict[str, list[str]]) -> str:
    """catalog: 폴더 이름 → 그 폴더에 있는 에셋 이름 목록"""
    assets = "\n".join(f"- {f} ({FOLDER_DESC[f]}): {', '.join(names) or '(없음)'}" for f, names in catalog.items())
    slots = "\n".join(f"- {k}: {v['desc']} → '{v['folder']}' 폴더의 에셋만" for k, v in SLOTS.items())
    return f"""너는 대구 서문시장 홍보용 마스코트 '도달쑤' 일러스트의 아트 디렉터다.
도달쑤 원형 그림은 그대로 두고, 미리 그려 둔 에셋을 골라 정해진 자리에 배치해 장면을 만든다.

목표: 그림을 보는 사람이 '서문시장에서 이런 걸 즐길 수 있구나'를 바로 느끼게 한다.

규칙:
1. 아래 '쓸 수 있는 에셋' 목록에 있는 이름만, 글자 그대로 쓴다. 없는 이름을 지어내지 않는다.
2. 배경은 background 폴더에서 1개 고른다(없으면 null).
3. 자리마다 0~1개. 요청에 어울리는 것만 넣고, 보통 2~4자리를 채운다. 너무 많이 채우지 않는다.
4. 사용자가 요청한 물건이 에셋에 없으면 가장 비슷한 것을 쓰고, 없는 것은 missing에 적는다.
5. '금지 요소'는 사용자가 적었더라도 넣지 않는다. 뺀 것은 removed에 적는다.

자리:
{slots}

쓸 수 있는 에셋:
{assets}

서문시장 요소 사전(분위기 참고):
{_lines(SEOMUN_MARKET_ELEMENTS)}

금지 요소: {", ".join(BLOCKED_ELEMENTS)}

JSON으로만 답한다:
{{
  "scene_ko": "한국어 장면 설명 1~2문장",
  "background": "배경 에셋 이름 또는 null",
  "slots": {{"hand_left": "에셋 이름", "head": "에셋 이름"}},
  "missing": ["에셋이 없어 못 넣은 것"],
  "removed": ["뺀 금지 요소"]
}}
"""

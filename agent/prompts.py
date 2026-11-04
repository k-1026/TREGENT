"""도달쑤 에이전트가 쓰는 원형 좌표, 포즈·소품·관광지 사전, Gemini 지시문.

원형 그림(images/dodalssu-basic.png)의 얼굴·머리·몸·다리는 픽셀 그대로 쓰고,
팔만 바꾼 포즈(poses/)와 미리 그려 둔 배경·소품(assets/)을 정해진 자리에 합성한다.
Gemini는 장면에 맞는 관광지·포즈·소품을 고르기만 한다.
"""

# 원형 이미지 크기(px). 이미지 배경은 투명하다.
CANVAS_W, CANVAS_H = 1145, 1374

# 앞 레이어가 덮을 수 없는 얼굴 영역(눈·코·수염·입). 마스크로 강제한다.
FACE_GUARD = {"cx": 560, "cy": 500, "rx": 255, "ry": 170}

# 포즈별 손 위치. tools/build_poses.py 의 팔 끝 좌표와 맞춘다.
POSES = {
    "basic": {"desc": "기본 자세, 두 팔을 내림", "hands": {"left_hand": (300, 1000), "right_hand": (820, 1000)}},
    "hold_right": {"desc": "오른손으로 음식·물건을 가슴 앞에 들어 올림", "hands": {"left_hand": (300, 1000), "right_hand": (700, 925)}},
    "hold_both": {"desc": "두 손을 모아 그릇·악기·큰 물건을 받쳐 듦", "hands": {"both_hands": (560, 960)}},
    "wave_right": {"desc": "오른손을 들어 인사함", "hands": {"left_hand": (300, 1000)}},
}

# 손 말고 늘 쓸 수 있는 자리: (기준점, 기준점이 소품 상자의 어디인지)
FIXED_SLOTS = {
    "head": ((560, 330), "bottom"),
    "neck": ((560, 765), "top"),
    "ground_left": ((170, 1335), "bottom"),
    "ground_right": ((975, 1335), "bottom"),
}

# 소품: 파일, 쓸 수 있는 자리 종류, 캔버스에서의 가로 크기(px), 손이 쥐는 지점(소품 상자 안 비율)
PROPS = {
    "씨앗호떡":    {"file": "hotteok.svg",       "kind": "hand",  "width": 270, "grip": (0.5, 0.82)},
    "납작만두":    {"file": "mandu.svg",         "kind": "hand",  "width": 260, "grip": (0.5, 0.8)},
    "칼국수":      {"file": "kalguksu.svg",      "kind": "both",  "width": 320, "grip": (0.5, 0.85)},
    "어묵꼬치":    {"file": "eomuk.svg",         "kind": "hand",  "width": 140, "grip": (0.5, 0.85)},
    "아이스크림":  {"file": "icecream.svg",      "kind": "hand",  "width": 170, "grip": (0.5, 0.82)},
    "풍선":        {"file": "balloon.svg",       "kind": "hand",  "width": 170, "grip": (0.5, 0.97)},
    "하모니카":    {"file": "harmonica.svg",     "kind": "hand",  "width": 220, "grip": (0.5, 0.6)},
    "카메라":      {"file": "camera.svg",        "kind": "hand",  "width": 220, "grip": (0.5, 0.75)},
    "통기타":      {"file": "guitar.svg",        "kind": "both",  "width": 470, "grip": (0.45, 0.55)},
    "장바구니":    {"file": "basket.svg",        "kind": "ground", "width": 230},
    "한복천 스카프": {"file": "scarf_hanbok.svg", "kind": "neck",  "width": 470},
    "오리배 머리띠": {"file": "duck_headband.svg", "kind": "head", "width": 640},
    "베레모":      {"file": "beret.svg",         "kind": "head",  "width": 520},
}
# "both" 소품은 두 손 자리에, "hand" 소품은 한 손 자리에도 두 손 자리에도 둘 수 있다
SLOT_KINDS = {"left_hand": {"hand"}, "right_hand": {"hand"}, "both_hands": {"hand", "both"},
              "head": {"head"}, "neck": {"neck"}, "ground_left": {"ground"}, "ground_right": {"ground"}}

# 대구 관광지 사전. 관광지 이름 → (배경 힌트, 어울리는 소품). 관광지를 적지 않은 입력은 서문시장.
# assets/backgrounds/<관광지 이름>.(png|jpg|webp|svg) 가 있으면 그 배경을 쓰고, 없으면 Gemini가 배경을 그린다.
DEFAULT_SPOT = "서문시장"
DAEGU_SPOTS = {
    "서문시장": (["줄지은 노점 천막", "야시장 줄 조명", "원단 진열"], ["씨앗호떡", "납작만두", "칼국수", "어묵꼬치", "장바구니", "한복천 스카프"]),
    "김광석다시그리기길": (["벽화 골목", "벤치"], ["통기타", "하모니카", "베레모", "카메라"]),
    "수성못": (["호수", "오리배", "버드나무", "가로등"], ["아이스크림", "풍선", "오리배 머리띠", "카메라"]),
    "근대골목": (["붉은 벽돌 성당", "담쟁이 언덕", "돌계단 골목"], ["카메라", "베레모"]),
    "앞산전망대": (["도시 야경", "전망 데크", "케이블카"], ["카메라"]),
    "이월드·83타워": (["놀이기구", "높은 전망 타워"], ["풍선", "아이스크림"]),
    "팔공산": (["산 능선", "단풍", "돌계단"], ["카메라"]),
    "동성로": (["번화가 거리", "버스킹 무대"], ["통기타", "아이스크림", "카메라"]),
    "약령시": (["한약방 거리", "약재 서랍장"], ["장바구니"]),
    "대구 10미 골목": (["골목 식당가", "숯불 화로"], ["납작만두", "칼국수"]),
}

# 그림에 넣지 않는 요소. 사용자가 입력에 적어도 뺀다.
BLOCKED_ELEMENTS = ["공구", "공구골목", "렌치", "스패너", "볼트", "너트", "드라이버", "망치", "펜치", "톱"]


def _lines(d: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in d.items())


def planner_instruction(spots_with_background: list[str]) -> str:
    spots = "\n".join(
        f"- {name}{' (배경 준비됨)' if name in spots_with_background else ''}: 풍경 = {', '.join(bg)} / 어울리는 소품 = {', '.join(props)}"
        for name, (bg, props) in DAEGU_SPOTS.items()
    )
    props = "\n".join(f"- {name}: {'두 손' if p['kind'] == 'both' else {'hand': '한 손 또는 두 손', 'head': '머리', 'neck': '목', 'ground': '바닥'}[p['kind']]}"
                      for name, p in PROPS.items())
    poses = "\n".join(f"- {k}: {v['desc']} (손 자리: {', '.join(v['hands']) or '없음'})" for k, v in POSES.items())
    return f"""너는 대구 관광 홍보 마스코트 '도달쑤' 일러스트의 아트 디렉터다.
도달쑤 원형 그림과 미리 그려 둔 포즈·소품·배경을 조합해 장면을 만든다. 너는 무엇을 쓸지 고르기만 한다.

목표: 그림을 보는 사람이 '대구의 이 관광지에서 이런 걸 즐길 수 있구나'를 바로 느끼게 한다.

규칙:
1. 입력에서 대구 관광지를 찾는다. 관광지를 적지 않았으면 {DEFAULT_SPOT}. 대구가 아닌 곳이면 가장 비슷한 대구 관광지로 바꾼다.
   사전에 없는 대구 관광지면 그 이름을 그대로 spot에 쓰고 spot_known을 false로 한다.
2. 포즈를 고른다. 음식이나 물건을 들면 hold_right(한 손) 또는 hold_both(그릇·악기 같은 큰 것), 인사하면 wave_right, 아니면 basic.
3. 소품은 아래 '소품 목록'의 이름만 글자 그대로 쓴다. 고른 포즈의 손 자리와 head, neck, ground_left, ground_right 자리에 0~1개씩.
   보통 2~3자리만 채운다. 관광지에 어울리는 소품을 우선한다.
4. 사용자가 원한 물건이 소품 목록에 없으면 가장 비슷한 것을 쓰고, 없는 것은 missing에 적는다.
5. '금지 요소'는 사용자가 적었더라도 넣지 않는다. 뺀 것은 removed에 적는다.
6. 고른 관광지가 '배경 준비됨'이 아니면 back_svg에 그 관광지 배경을 SVG로 그린다. 준비된 곳이면 back_svg는 빈 문자열.
   back_svg 규칙: viewBox 0 0 {CANVAS_W} {CANVAS_H} 전체를 채움, <svg> 태그 없이 안쪽 요소만, 태그는 g/path/rect/circle/ellipse/line/polyline/polygon만,
   글자·그라데이션·이미지 금지, 단색 면 + 굵은 검은 외곽선(stroke="#111" stroke-width 8~10), 하늘 → 먼 풍경 → 대표 구조물 → 바닥 순으로 층을 나누고
   가운데(x 250~900)는 단순하게, 도형 60~150개.

포즈:
{poses}

소품 목록 (이름: 둘 수 있는 자리):
{props}

대구 관광지 사전:
{spots}

금지 요소: {", ".join(BLOCKED_ELEMENTS)}

JSON으로만 답한다:
{{
  "spot": "관광지 이름",
  "spot_known": true,
  "pose": "hold_right",
  "items": {{"right_hand": "씨앗호떡", "neck": "한복천 스카프"}},
  "scene_ko": "한국어 장면 설명 1~2문장",
  "missing": [],
  "removed": [],
  "back_svg": ""
}}
"""

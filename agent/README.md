# 🦦 도달쑤 × 서문시장 그림 에이전트

장면을 글로 적으면, **원형 도달쑤**(`images/dodalssu-basic.png`)가 서문시장을 즐기는 그림을 만들어 줍니다.

## 동작 순서

1. 미리 그려 둔 **소품·배경 에셋**을 `assets/` 폴더에 넣어 둡니다. 넣는 법과 ChatGPT로 만드는 법은 [assets/README.md](assets/README.md)에 있어요.
2. **Gemini**(무료 글 모델)가 입력 글을 읽고, 어떤 배경과 소품을 어느 자리(손, 머리, 목, 몸, 등 뒤, 바닥)에 둘지 고릅니다. 공구류는 뺍니다.
3. 원형 도달쑤 그림을 **픽셀 그대로** 가운데 두고, 고른 에셋을 정해진 자리에 합성합니다. 소품은 얼굴(눈·코·수염·입)을 덮지 못하게 막혀 있어요.

자리 좌표와 요소 사전은 [`prompts.py`](prompts.py)에서 고칠 수 있어요.

## 실행

1. Python 3.10 이상을 설치합니다.
2. `agent` 폴더에서 패키지를 설치합니다.
   ```bash
   pip install -r requirements.txt
   ```
3. `.env.example`을 `.env`로 복사하고 `GEMINI_API_KEY`를 채웁니다. 키는 aistudio.google.com에서 발급합니다.
   - 모델이 붐비거나(503) 한도를 넘으면(429) `.env`의 모델 목록에서 다음 모델로 자동으로 넘어갑니다.
4. 서버를 켭니다.
   ```bash
   python -m uvicorn main:app --port 8000
   ```
5. 브라우저에서 http://localhost:8000 을 엽니다.

결과 그림은 `agent/outputs/`에 SVG로 저장되고, 화면에서 PNG로 내려받을 수 있어요.

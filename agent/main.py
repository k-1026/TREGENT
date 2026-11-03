"""도달쑤 × 서문시장 그림 에이전트 웹 서버. 실행: python -m uvicorn main:app (agent 폴더에서)"""

from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from pipeline import BASE_IMAGE, OUTPUT_DIR, AgentError, generate  # noqa: E402

app = FastAPI(title="도달쑤 × 서문시장")
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUT_DIR), name="outputs")


class GenerateRequest(BaseModel):
    text: str


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/base.png")
def base_image():
    return FileResponse(BASE_IMAGE)


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "그리고 싶은 장면을 적어 주세요.")
    try:
        return generate(text)
    except AgentError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"생성 중 오류가 났어요: {e}")

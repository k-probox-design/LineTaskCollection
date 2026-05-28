from fastapi import FastAPI

from app.logging_config import setup_logging

setup_logging()

from app.line_webhook import router as line_router  # noqa: E402  (logger 初期化を import より先に実行するため)

app = FastAPI(title="LineTaskCollection Receiver")
app.include_router(line_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

from fastapi import FastAPI

from app.line_webhook import router as line_router

app = FastAPI(title="LineTaskCollection Receiver")
app.include_router(line_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

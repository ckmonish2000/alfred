import logging

from fastapi import FastAPI

from app.features.video_chat.router import router as video_chat_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Alfred")
app.include_router(video_chat_router)


@app.get("/health")
def health():
    return {"status": "ok"}

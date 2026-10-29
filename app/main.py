# -*- coding: utf-8 -*-
"""
رفيق — نظام محادثة صوتي عربي مدمج:
  Jais-ASR (استماع) + Jais-3-7B (تفكير) + SILMA TTS (كلام)
مع واجهة محادثة، فوترة بالدقيقة، مفاتيح API، وحساب مالك بصلاحيات.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .pipeline import state as pstate
from .routes import admin, auth, billing as billing_routes, chat, keys, openai_api, voice

log = logging.getLogger("rafeeq")


def warm_models() -> None:
    """تحميل النماذج الثلاثة في خيط خلفي مع تحديث الحالة للواجهة."""
    from .pipeline.asr import get_asr
    from .pipeline.llm import get_llm
    from .pipeline.tts import get_tts

    steps = [
        ("tts", get_tts, "SILMA TTS"),
        ("asr", get_asr, "Jais-ASR"),
        ("llm", get_llm, "Jais-3-7B"),
    ]
    for key, fn, label in steps:
        if pstate.STATE[key].status == "ready":
            continue
        t0 = time.time()
        try:
            log.info("تحميل %s ...", label)
            fn()
            log.info("جاهز %s في %.1fs", label, time.time() - t0)
        except Exception as e:  # noqa: BLE001
            log.error("فشل تحميل %s: %s", label, e)
            pstate.mark_error(key, str(e)[:400])
    log.info("حالة النماذج: %s", {k: v.status for k, v in pstate.STATE.items()})


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    log.info("قاعدة البيانات جاهزة: %s", config.DB_PATH)
    if db.get_setting("warm_models", "1") == "1":
        threading.Thread(target=warm_models, daemon=True, name="warm-models").start()
    yield


app = FastAPI(
    title="رفيق — مساعدك الصوتي العربي",
    description="دمج Jais-ASR + Jais-3-7B + SILMA TTS في نظام واحد بفوترة بالدقيقة.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# المسارات
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(keys.router)
app.include_router(billing_routes.router)
app.include_router(admin.router)
app.include_router(openai_api.router)
app.include_router(voice.router)

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/api/status")
def status(request: Request):
    """حالة النظام والنماذج (تُستدعى دورياً من الواجهة)."""
    return {
        "app": db.get_setting("app_name", config.DEFAULT_SETTINGS["app_name"]),
        "models": pstate.snapshot(),
        "ready": pstate.all_ready(),
        "owner_exists": db.owner_exists(),
        "allow_register": db.get_setting("allow_register", "1") == "1",
        "billing": {
            "price_per_minute": float(db.get_setting("price_per_minute", "0.5")),
            "currency": db.get_setting("currency", "ر.س"),
        },
    }


@app.get("/api/health")
def health():
    return {"ok": True, "time": db.now_iso()}


@app.get("/")
def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.get("/{full_path:path}")
def spa(full_path: str):
    """توجيه كل المسارات غير المعروفة إلى الواجهة (SPA)."""
    candidate = config.STATIC_DIR / full_path
    if candidate.is_file():
        return FileResponse(str(candidate))
    return FileResponse(str(config.STATIC_DIR / "index.html"))


def main() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
        reload=False,
    )


if __name__ == "__main__":
    main()

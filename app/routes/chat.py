# -*- coding: utf-8 -*-
"""المحادثة النصية: جلسات محفوظة + بث SSE مع فوترة بالدقيقة."""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .. import billing, db, security
from ..pipeline import llm as llm_mod
from ..pipeline.sentence import clean_for_speech
from ..pipeline.stream_util import aiter_threaded, run_sync
from .deps import get_user, is_staff

router = APIRouter(prefix="/api", tags=["chat"])

HISTORY_LIMIT = 20
HISTORY_CHAR_LIMIT = 6000


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: int | None = None
    voice: bool = False


class SessionIn(BaseModel):
    title: str = Field(default="", max_length=120)


# --------------------------------------------------------------- الجلسات
@router.get("/sessions")
def list_sessions(user: dict = Depends(get_user)):
    rows = db.query(
        "SELECT id, title, created_at, updated_at FROM chat_sessions "
        "WHERE user_id=? ORDER BY updated_at DESC LIMIT 100",
        (user["id"],),
    )
    return {"sessions": rows}


@router.post("/sessions")
def create_session(body: SessionIn, user: dict = Depends(get_user)):
    now = db.now_iso()
    sid = db.execute(
        "INSERT INTO chat_sessions(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
        (user["id"], (body.title or "محادثة جديدة").strip(), now, now),
    )
    return {"id": sid, "title": body.title or "محادثة جديدة"}


@router.get("/sessions/{sid}/messages")
def session_messages(sid: int, user: dict = Depends(get_user)):
    sess = db.one(
        "SELECT * FROM chat_sessions WHERE id=? AND user_id=?", (sid, user["id"])
    )
    if not sess:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة")
    msgs = db.query(
        "SELECT id, role, content, created_at FROM chat_messages "
        "WHERE session_id=? ORDER BY id",
        (sid,),
    )
    return {"session": sess, "messages": msgs}


@router.delete("/sessions/{sid}")
def delete_session(sid: int, user: dict = Depends(get_user)):
    sess = db.one(
        "SELECT id FROM chat_sessions WHERE id=? AND user_id=?", (sid, user["id"])
    )
    if not sess:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة")
    db.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
    return {"ok": True}


# --------------------------------------------------------------- المحادثة
def _load_history(session_id: int) -> list[dict]:
    rows = db.query(
        "SELECT role, content FROM (SELECT role, content, id FROM chat_messages "
        "WHERE session_id=? ORDER BY id DESC LIMIT ?) ORDER BY id",
        (session_id, HISTORY_LIMIT),
    )
    msgs: list[dict] = []
    total = 0
    for r in reversed(rows):
        total += len(r["content"])
        if total > HISTORY_CHAR_LIMIT and msgs:
            break
        msgs.append({"role": r["role"], "content": r["content"]})
    return msgs


def _system_prompt(voice: bool) -> str:
    if voice:
        return db.get_setting("system_prompt_voice")
    return db.get_setting("system_prompt_text")


@router.post("/chat")
async def chat(body: ChatIn, user: dict = Depends(get_user)):
    if not security.can(user["role"], "chat.use"):
        raise HTTPException(status_code=403, detail="لا تملك صلاحية المحادثة")
    if not is_staff(user) and not billing.has_minutes(user["id"]):
        raise HTTPException(
            status_code=402,
            detail="انتهت دقائقك — اشترك أو اشحن رصيدك للمتابعة",
        )

    # الجلسة
    session_id = body.session_id
    if session_id:
        sess = db.one(
            "SELECT id FROM chat_sessions WHERE id=? AND user_id=?",
            (session_id, user["id"]),
        )
        if not sess:
            raise HTTPException(status_code=404, detail="الجلسة غير موجودة")
    else:
        now = db.now_iso()
        title = body.message.strip().replace("\n", " ")[:40] or "محادثة جديدة"
        session_id = db.execute(
            "INSERT INTO chat_sessions(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (user["id"], title, now, now),
        )

    db.execute(
        "INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
        (session_id, "user", body.message, db.now_iso()),
    )

    history = _load_history(session_id)
    messages = [{"role": "system", "content": _system_prompt(body.voice)}]
    messages += history
    messages.append({"role": "user", "content": body.message})

    settings = db.get_settings(
        [
            "llm_max_new_tokens_voice",
            "llm_max_new_tokens_text",
            "llm_temperature",
            "llm_top_p",
            "llm_top_k",
            "reasoning_effort_voice",
            "reasoning_effort_text",
        ]
    )
    max_new = int(
        settings["llm_max_new_tokens_voice"]
        if body.voice
        else settings["llm_max_new_tokens_text"]
    )
    effort = settings["reasoning_effort_voice"] if body.voice else settings["reasoning_effort_text"]

    t0 = time.time()
    stop_event = __import__("threading").Event()
    assistant_parts: list[str] = []

    def _stream():
        return llm_mod.get_llm().stream(
            messages,
            max_new_tokens=max_new,
            temperature=float(settings["llm_temperature"]),
            top_p=float(settings["llm_top_p"]),
            top_k=int(settings["llm_top_k"]),
            reasoning_effort=effort,
            stop_event=stop_event,
        )

    async def event_gen():
        yield _sse({"type": "start", "session_id": session_id})
        try:
            gen = aiter_threaded(_stream(), stop_event)
            async for kind, text in gen:
                if kind == "think":
                    yield _sse({"type": "think"})
                elif kind == "content":
                    assistant_parts.append(text)
                    yield _sse({"type": "delta", "text": text})
            reply = "".join(assistant_parts).strip()
            if reply:
                db.execute(
                    "INSERT INTO chat_messages(session_id,role,content,created_at) "
                    "VALUES(?,?,?,?)",
                    (session_id, "assistant", reply, db.now_iso()),
                )
                db.execute(
                    "UPDATE chat_sessions SET updated_at=? WHERE id=?",
                    (db.now_iso(), session_id),
                )
            usage = {"seconds": round(time.time() - t0, 2), "charged": 0}
            if not is_staff(user):
                r = billing.charge(
                    user["id"],
                    usage["seconds"],
                    "api_chat" if body.voice else "chat",
                    detail=(body.message[:60]),
                    session_id=str(session_id),
                )
                usage = {
                    "seconds": usage["seconds"],
                    "charged": r["charged"],
                    "plan_left": r["plan_left"],
                    "balance_left": r["balance_left"],
                    "ok": r["ok"],
                }
                if not r["ok"]:
                    yield _sse({"type": "billing_exhausted", "usage": usage})
            yield _sse({"type": "done", "session_id": session_id, "usage": usage})
        except Exception as e:  # noqa: BLE001
            yield _sse({"type": "error", "message": str(e)[:400]})

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


# --------------------------------------------------------------- نطق الردود (زر 🔊)
class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speed: float | None = Field(default=None, ge=0.5, le=2.0)


@router.post("/tts")
async def tts(body: TTSIn, user: dict = Depends(get_user)):
    """يحوّل نصًا إلى صوت WAV — يعمل حتى على الاستضافة المجانية (نموذج الكلام الأصلي SILMA)."""
    if not billing.has_minutes(user["id"]) and not is_staff(user):
        raise HTTPException(status_code=402, detail="انتهت دقائقك")
    t0 = time.time()
    from ..pipeline.tts import get_tts
    from ..pipeline.audio import pcm16_to_wav

    speed = body.speed if body.speed is not None else float(db.get_setting("tts_speed", "1.0") or 1.0)
    pcm, sr = await run_sync(get_tts().synthesize, body.text, speed)
    secs = time.time() - t0
    charged = 0
    st = billing.minutes_state(user["id"])
    if not is_staff(user):
        r = billing.charge(user["id"], secs, "speech", detail="نطق الرد الصوتي")
        charged = r["charged"]
        st = billing.minutes_state(user["id"])
        if not r["ok"]:
            raise HTTPException(status_code=402, detail="نفدت دقائقك")
    return Response(
        content=pcm16_to_wav(pcm, sr),
        media_type="audio/wav",
        headers={
            "X-Minutes-Charged": str(charged),
            "X-Minutes-Plan-Left": str(st.get("plan_left", 0)),
            "X-Minutes-Balance-Left": str(st.get("balance_left", 0)),
            "X-Billing-Unit": "minute",
        },
    )

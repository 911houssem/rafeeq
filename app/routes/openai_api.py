# -*- coding: utf-8 -*-
"""
واجهة API متوافقة مع OpenAI (للتطبيقات الخارجية):
  POST /v1/chat/completions   محادثة نصية (تدفق اختياري)
  POST /v1/audio/transcriptions  تحويل الصوت إلى نص
  POST /v1/audio/speech       تحويل النص إلى صوت
  GET  /v1/models   /v1/usage
المصادقة: مفتاح API (sk-...) أو رمز الدخول — الفوترة بالدقيقة.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .. import billing, db
from ..pipeline.stream_util import aiter_threaded, run_sync
from .deps import get_user, is_staff

router = APIRouter(prefix="/v1", tags=["openai-api"])

MODEL_NAME = "jais-3-7b"


def _usage_headers(charged: int, state: dict) -> dict:
    return {
        "X-Minutes-Charged": str(charged),
        "X-Minutes-Plan-Left": str(state.get("plan_left", 0)),
        "X-Minutes-Balance-Left": str(state.get("balance_left", 0)),
        "X-Billing-Unit": "minute",
    }


class OAIChatIn(BaseModel):
    model: str = MODEL_NAME
    messages: list[dict]
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, le=8192)


@router.post("/chat/completions")
async def chat_completions(body: OAIChatIn, user: dict = Depends(get_user)):
    if not billing.has_minutes(user["id"]) and not is_staff(user):
        raise HTTPException(
            status_code=402,
            detail={"error": "انتهت دقائقك — اشترك أو اشحن رصيدك", "type": "insufficient_minutes"},
        )
    t0 = time.time()
    settings = db.get_settings(
        [
            "llm_max_new_tokens_text",
            "llm_temperature",
            "llm_top_p",
            "llm_top_k",
            "reasoning_effort_text",
            "system_prompt_text",
        ]
    )
    messages = list(body.messages)
    if not messages or messages[0].get("role") != "system":
        messages = [{"role": "system", "content": settings["system_prompt_text"]}] + messages

    from ..pipeline.llm import get_llm

    stop = __import__("threading").Event()
    temp = body.temperature if body.temperature is not None else float(settings["llm_temperature"])
    top_p = body.top_p if body.top_p is not None else float(settings["top_p"] if "top_p" in settings else settings["llm_top_p"])
    max_new = body.max_tokens or int(settings["llm_max_new_tokens_text"])
    rid = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())

    def _stream():
        return get_llm().stream(
            messages,
            max_new_tokens=max_new,
            temperature=temp,
            top_p=top_p,
            top_k=int(settings["llm_top_k"]),
            reasoning_effort=settings["reasoning_effort_text"],
            stop_event=stop,
        )

    async def _finish() -> tuple[int, dict]:
        secs = time.time() - t0
        if is_staff(user):
            return 0, {"seconds": round(secs, 2)}
        r = billing.charge(user["id"], secs, "api_chat", "OpenAI chat", None)
        return r["charged"], {
            "seconds": round(secs, 2),
            "plan_left": r["plan_left"],
            "balance_left": r["balance_left"],
        }

    if not body.stream:
        parts: list[str] = []
        gen = aiter_threaded(_stream(), stop)
        async for kind, piece in gen:
            if kind == "content":
                parts.append(piece)
        text = "".join(parts)
        charged, usage = await _finish()
        return {
            "id": rid,
            "object": "chat.completion",
            "created": created,
            "model": body.model,
            "choices": [
                {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
            ],
            "usage": {"billing": {"unit": "minute", "charged": charged, **usage}},
            "x_minutes_charged": charged,
        }

    async def event_gen():
        try:
            gen = aiter_threaded(_stream(), stop)
            async for kind, piece in gen:
                if kind != "content":
                    continue
                chunk = {
                    "id": rid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": body.model,
                    "choices": [
                        {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                    ],
                }
                yield "data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n"
            charged, usage = await _finish()
            tail = {
                "id": rid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": body.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"billing": {"unit": "minute", "charged": charged, **usage}},
            }
            yield "data: " + json.dumps(tail, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:  # noqa: BLE001
            err = {"error": {"message": str(e)[:300], "type": "server_error"}}
            yield "data: " + json.dumps(err, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------- الصوت
class OAISpeechIn(BaseModel):
    model: str = MODEL_NAME
    input: str = Field(min_length=1, max_length=4000)
    voice: str = "ref"
    speed: float | None = Field(default=None, ge=0.5, le=2.0)


@router.post("/audio/speech")
async def audio_speech(body: OAISpeechIn, user: dict = Depends(get_user)):
    if not billing.has_minutes(user["id"]) and not is_staff(user):
        raise HTTPException(status_code=402, detail="انتهت دقائقك")
    t0 = time.time()
    from ..pipeline.tts import get_tts

    speed = body.speed if body.speed is not None else float(db.get_setting("tts_speed", "1.0"))
    pcm, sr = await run_sync(get_tts().synthesize, body.input, speed)
    secs = time.time() - t0
    from ..pipeline.audio import pcm16_to_wav

    charged = 0
    state = billing.minutes_state(user["id"])
    if not is_staff(user):
        r = billing.charge(user["id"], secs, "speech", "OpenAI speech", None)
        charged = r["charged"]
        state = billing.minutes_state(user["id"])
        if not r["ok"]:
            raise HTTPException(status_code=402, detail="نفدت دقائقك")
    wav = pcm16_to_wav(pcm, sr)
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'attachment; filename="speech.wav"',
            **_usage_headers(charged, state),
        },
    )


@router.post("/audio/transcriptions")
async def audio_transcriptions(
    file: UploadFile = File(...),
    model: str = MODEL_NAME,
    language: str | None = None,
    user: dict = Depends(get_user),
):
    if not billing.has_minutes(user["id"]) and not is_staff(user):
        raise HTTPException(status_code=402, detail="انتهت دقائقك")
    raw = await file.read()
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="الملف أكبر من 25MB")
    from ..pipeline.audio import wav_to_pcm16

    try:
        pcm, sr = wav_to_pcm16(raw)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"تعذر قراءة الصوت: {e}")

    t0 = time.time()
    from ..pipeline.asr import get_asr

    res = await run_sync(get_asr().transcribe, pcm, sr, language)
    secs = time.time() - t0
    charged = 0
    state = billing.minutes_state(user["id"])
    if not is_staff(user):
        r = billing.charge(user["id"], secs, "transcribe", "OpenAI transcription", None)
        charged = r["charged"]
        state = billing.minutes_state(user["id"])
        if not r["ok"]:
            raise HTTPException(status_code=402, detail="نفدت دقائقك")
    return {
        "text": res["text"],
        "language": res.get("language"),
        "usage": {"billing": {"unit": "minute", "charged": charged, "seconds": round(secs, 2)}},
        **{k.lower().replace("-", "_"): v for k, v in _usage_headers(charged, state).items()},
    }


@router.get("/models")
def models(user: dict = Depends(get_user)):
    return {
        "object": "list",
        "data": [
            {"id": MODEL_NAME, "object": "model", "owned_by": "jais"},
            {"id": "jais-asr", "object": "model", "owned_by": "jais"},
            {"id": "silma-tts", "object": "model", "owned_by": "silma"},
        ],
    }


@router.get("/usage")
def usage(user: dict = Depends(get_user)):
    state = billing.minutes_state(user["id"])
    return {
        "object": "usage",
        "unit": "minute",
        "billing": state,
        "price_per_minute": float(db.get_setting("price_per_minute", "0.5")),
        "recent": billing.usage_history(user["id"], 10),
    }

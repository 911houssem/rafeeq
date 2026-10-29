# -*- coding: utf-8 -*-
"""
الجلسة الصوتية اللحظية (WebSocket):
الميكروفون ← VAD ← Jais-ASR ← Jais-3-7B ← SILMA TTS ← سماعة المستخدم.
مع: مقاطعة طبيعية (barge-in)، بث الجُمل أولًا بأول، وفوترة حيّة بالدقيقة.
"""
from __future__ import annotations

import asyncio
import base64
import json
import queue as pyqueue
import threading
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import billing, db, security
from ..pipeline import state as pstate
from ..pipeline.audio import pcm_duration, pcm16_to_wav, rms
from ..pipeline.sentence import SentenceStreamer, clean_for_speech
from ..pipeline.stream_util import aiter_threaded, run_sync
from .chat import _load_history, _system_prompt
from .deps import public_user

router = APIRouter()

IDLE, SPEAKING, PROCESSING, REPLYING = "idle", "speaking", "processing", "replying"


class VoiceSession:
    def __init__(self, ws: WebSocket, user: dict):
        self.ws = ws
        self.user = user
        self.staff = user.get("role") in ("owner", "admin")
        self.state = IDLE
        self.buf = bytearray()
        self.last_voice = 0.0
        self.turn = 0                      # عدّاد الجولات (لإلغاء القديم)
        self.stop_event: threading.Event | None = None
        self.respond_task: asyncio.Task | None = None
        self.processing_task: asyncio.Task | None = None
        self.utterance_task: asyncio.Task | None = None
        # الفوترة الحيّة
        self.active = False
        self.active_seconds = 0.0
        self.charged = 0
        self.meter_task: asyncio.Task | None = None
        self.session_id: int | None = None
        # إعدادات الجلسة
        s = db.get_settings(["vad_silence_ms", "vad_energy", "vad_min_speech_ms"])
        self.silence_s = max(0.3, int(s["vad_silence_ms"]) / 1000.0)
        self.threshold = float(s["vad_energy"])
        self.min_speech_s = max(0.1, int(s["vad_min_speech_ms"]) / 1000.0)
        self.speech_started_at = 0.0

    # ================================================== الرسائل الصادرة
    async def send(self, obj: dict):
        try:
            await self.ws.send_json(obj)
        except Exception:  # noqa: BLE001
            pass

    async def send_status(self, stage: str, **kw):
        await self.send({"type": "status", "stage": stage, **kw})

    # =================================================> الحلقة الرئيسية
    async def run(self):
        await self.send(
            {
                "type": "ready",
                "user": public_user(self.user),
                "models": pstate.snapshot(),
            }
        )
        self.meter_task = asyncio.create_task(self._meter())
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data is not None:
                    self._on_audio(data)
                    continue
                text = msg.get("text")
                if not text:
                    continue
                try:
                    ctrl = json.loads(text)
                except json.JSONDecodeError:
                    continue
                await self._on_control(ctrl)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass
        finally:
            await self._teardown()

    # ================================================== التحكم
    async def _on_control(self, c: dict):
        t = c.get("type")
        if t == "start":
            await self.send(
                {
                    "type": "session",
                    "minutes": billing.minutes_state(self.user["id"]),
                    "free": self.staff,
                }
            )
        elif t == "cancel":
            self._interrupt()
            await self.send({"type": "interrupt"})
        elif t == "end":
            await self._teardown()
            try:
                await self.ws.close(code=1000)
            except Exception:  # noqa: BLE001
                pass
        elif t == "text":
            body = (c.get("text") or "").strip()
            if not body:
                return
            voice_reply = bool(c.get("voice", True))
            if not self._ensure_access():
                return
            self._start_billing()
            self._interrupt(new_turn=True)
            self.state = PROCESSING
            self.processing_task = asyncio.create_task(
                self._text_turn(body, voice_reply)
            )

    # ================================================== الصوت الوارد (VAD)
    def _on_audio(self, frame: bytes):
        v = rms(frame)
        now = time.monotonic()
        if self.state == SPEAKING:
            self.buf.extend(frame)
            if v > self.threshold:
                self.last_voice = now
            elif now - self.last_voice >= self.silence_s:
                dur = pcm_duration(bytes(self.buf), 16000)
                self.state = IDLE
                if dur >= self.min_speech_s:
                    pcm = bytes(self.buf)
                    self.buf.clear()
                    self.utterance_task = asyncio.ensure_future(
                        self._utterance_turn(pcm)
                    )
                else:
                    self.buf.clear()
        else:
            if v > self.threshold:
                # بداية كلام جديد → مقاطعة أي رد جارٍ
                if self.state in (PROCESSING, REPLYING):
                    self._interrupt(new_turn=True)
                    self.send_nowait({"type": "interrupt"})
                self.state = SPEAKING
                self.last_voice = now
                self.speech_started_at = now
                self.buf = bytearray(frame)
                asyncio.ensure_future(
                    self.send({"type": "speech", "state": "start"})
                )

    def send_nowait(self, obj: dict):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.send(obj))
        except RuntimeError:
            pass

    # ================================================== دور المحادثة
    def _ensure_access(self) -> bool:
        if self.staff or billing.has_minutes(self.user["id"]):
            return True
        self.send_nowait(
            {
                "type": "error",
                "code": "no_minutes",
                "message": "انتهت دقائقك — اشترك أو اشحن رصيدك للمتابعة",
            }
        )
        return False

    def _start_billing(self):
        if self.staff:
            return
        if self.meter_task is None or self.meter_task.done():
            self.meter_task = asyncio.ensure_future(self._meter())
        if not self.active:
            self.active = True
            # لا يبدأ الجولة دون رصيد دقيقة واحدة
            st = billing.minutes_state(self.user["id"])
            if st["total_left"] <= 0:
                self.active = False
                self.send_nowait(
                    {
                        "type": "error",
                        "code": "no_minutes",
                        "message": "لا يوجد رصيد دقائق كافٍ لبدء الجولة",
                    }
                )

    async def _meter(self):
        """خصم دقيقة كل دقيقة استخدام فعلي (بينما الجلسة نشطة)."""
        while True:
            await asyncio.sleep(1)
            if not self.active or self.staff:
                continue
            self.active_seconds += 1
            target = billing.seconds_to_minutes(self.active_seconds)
            if target > self.charged:
                r = billing.charge(
                    self.user["id"],
                    60.0 * (target - self.charged),
                    "voice",
                    "جلسة صوتية",
                    session_id=str(self.session_id or ""),
                )
                self.charged += r["charged"]
                await self.send(
                    {
                        "type": "billing",
                        "charged": self.charged,
                        "plan_left": r["plan_left"],
                        "balance_left": r["balance_left"],
                        "minutes": billing.minutes_state(self.user["id"]),
                    }
                )
                if not r["ok"]:
                    self._interrupt()
                    await self.send(
                        {
                            "type": "error",
                            "code": "no_minutes",
                            "message": "نفدت دقائقك — تم إيقاف الجلسة",
                        }
                    )
                    self.active = False

    async def _utterance_turn(self, pcm: bytes):
        """صوت المستخدم انتهى → تفريغ → رد."""
        if not self._ensure_access():
            return
        self._start_billing()
        if not self.active and not self.staff:
            return
        self.turn += 1
        my_turn = self.turn
        self.state = PROCESSING
        await self.send({"type": "speech", "state": "end"})
        await self.send_status("asr")

        try:
            from ..pipeline.asr import get_asr

            res = await run_sync(get_asr().transcribe, pcm, 16000)
        except Exception as e:  # noqa: BLE001
            await self.send(
                {"type": "error", "code": "asr_failed", "message": str(e)[:300]}
            )
            self.state = IDLE
            return

        if my_turn != self.turn:  # أُلغيت الجولة
            return
        text = (res.get("text") or "").strip()
        await self.send(
            {
                "type": "transcript",
                "text": text,
                "language": res.get("language"),
                "empty": not bool(text),
            }
        )
        if not text:
            self.state = IDLE
            await self.send_status("idle")
            return
        await self._text_turn(text, voice_reply=True, from_speech=True)

    async def _text_turn(self, text: str, voice_reply: bool, from_speech: bool = False):
        my_turn = self.turn
        try:
            await self._respond(text, voice_reply, my_turn, from_speech)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            await self.send(
                {"type": "error", "code": "respond_failed", "message": str(e)[:400]}
            )
            self.state = IDLE
            await self.send_status("idle")

    # ================================================== الرد (LLM → TTS)
    async def _respond(
        self, text: str, voice_reply: bool, my_turn: int, from_speech: bool
    ):
        from ..pipeline import state as pstate

        snap = pstate.snapshot()
        not_ready = [v["label"] for v in snap.values() if v["status"] != "ready"]
        if not_ready:
            await self.send(
                {
                    "type": "error",
                    "code": "loading",
                    "message": "النماذج قيد التحميل: " + "، ".join(not_ready),
                }
            )
            self.state = IDLE
            return

        self.state = REPLYING
        session_id = self._ensure_session(text)
        history = _load_history(session_id)
        self._save_user_message(session_id, text)
        settings = db.get_settings(
            [
                "llm_max_new_tokens_voice",
                "llm_temperature",
                "llm_top_p",
                "llm_top_k",
                "reasoning_effort_voice",
                "tts_speed",
            ]
        )
        messages = [{"role": "system", "content": _system_prompt(True)}]
        messages += history
        messages.append({"role": "user", "content": text})

        self.stop_event = threading.Event()
        stop = self.stop_event
        await self.send_status("llm")

        from ..pipeline.llm import get_llm

        def _stream():
            return get_llm().stream(
                messages,
                max_new_tokens=int(settings["llm_max_new_tokens_voice"]),
                temperature=float(settings["llm_temperature"]),
                top_p=float(settings["llm_top_p"]),
                top_k=int(settings["llm_top_k"]),
                reasoning_effort=settings["reasoning_effort_voice"],
                stop_event=stop,
            )

        audio_q: asyncio.Queue = asyncio.Queue(maxsize=8)
        tts_task = None
        if voice_reply:
            tts_task = asyncio.create_task(self._tts_worker(audio_q, stop, my_turn))

        splitter = SentenceStreamer()
        parts: list[str] = []
        thinking_sent = False
        try:
            gen = aiter_threaded(_stream(), stop)
            async for kind, piece in gen:
                if my_turn != self.turn or stop.is_set():
                    break
                if kind == "think":
                    if not thinking_sent:
                        thinking_sent = True
                        await self.send_status("thinking")
                    continue
                if kind == "content":
                    if not parts:
                        await self.send_status("speaking")
                    parts.append(piece)
                    await self.send({"type": "delta", "text": piece})
                    for sent in splitter.feed(piece):
                        if voice_reply:
                            await audio_q.put(sent)
            if not stop.is_set() and my_turn == self.turn:
                for sent in splitter.flush():
                    if voice_reply:
                        await audio_q.put(sent)
        finally:
            if voice_reply and tts_task is not None:
                try:
                    await audio_q.put(None)
                    await tts_task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass

        if my_turn != self.turn or stop.is_set():
            return  # أُلغي الرد (مقاطعة)

        reply = "".join(parts).strip()
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
        await self.send(
            {
                "type": "done",
                "session_id": session_id,
                "minutes": billing.minutes_state(self.user["id"])
                if not self.staff
                else None,
            }
        )
        if not self.staff:
            self.active_seconds += 0.5  # تأمين دقة الفوترة عند النهاية
        self.state = IDLE
        await self.send_status("idle")

    async def _tts_worker(
        self, q: asyncio.Queue, stop: threading.Event, my_turn: int
    ):
        seq = 0
        first = True
        while True:
            sent = await q.get()
            if sent is None:
                break
            if stop.is_set() or my_turn != self.turn:
                break
            clean = clean_for_speech(sent)
            if not clean:
                continue
            if first:
                first = False
                await self.send_status("tts")
            try:
                from ..pipeline.tts import get_tts

                speed = float(db.get_setting("tts_speed", "1.0") or 1.0)
                pcm, sr = await run_sync(get_tts().synthesize, clean, speed)
            except Exception as e:  # noqa: BLE001
                await self.send(
                    {"type": "error", "code": "tts_failed", "message": str(e)[:300]}
                )
                continue
            if stop.is_set() or my_turn != self.turn:
                break
            wav = pcm16_to_wav(pcm, sr)
            await self.send(
                {
                    "type": "audio",
                    "data": base64.b64encode(wav).decode(),
                    "seq": seq,
                    "sr": sr,
                }
            )
            seq += 1
        await self.send({"type": "audio_end", "seq": seq})

    # ================================================== الجلسات المحفوظة
    def _ensure_session(self, first_text: str) -> int:
        if self.session_id:
            return self.session_id
        now = db.now_iso()
        title = first_text.replace("\n", " ")[:40] or "محادثة صوتية"
        self.session_id = db.execute(
            "INSERT INTO chat_sessions(user_id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (self.user["id"], title, now, now),
        )
        return self.session_id

    def _save_user_message(self, session_id: int, text: str):
        db.execute(
            "INSERT INTO chat_messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
            (session_id, "user", text, db.now_iso()),
        )

    # ================================================== المقاطعة والإنهاء
    def _interrupt(self, new_turn: bool = True):
        if new_turn:
            self.turn += 1
        if self.stop_event is not None:
            self.stop_event.set()
        for t in (self.respond_task, self.processing_task, self.utterance_task):
            if t is not None and not t.done():
                t.cancel()
        self.state = IDLE

    async def _teardown(self):
        # الفوترة النهائية للجزء من الدقيقة
        if self.active and not self.staff and self.active_seconds > 0:
            target = billing.seconds_to_minutes(self.active_seconds)
            delta = target - self.charged
            if delta > 0:
                billing.charge(
                    self.user["id"],
                    60.0 * delta,
                    "voice",
                    "ختام جلسة صوتية",
                    session_id=str(self.session_id or ""),
                )
            self.active = False
        self._interrupt(new_turn=False)
        if self.meter_task is not None and not self.meter_task.done():
            self.meter_task.cancel()
        await self.send({"type": "closed"})


@router.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    token = ws.query_params.get("token") or ""
    user = None
    if token.startswith("sk-"):
        from .deps import user_from_api_key

        user = user_from_api_key(token)
    elif token:
        payload = security.decode_token(token)
        if payload:
            user = db.one("SELECT * FROM users WHERE id=?", (int(payload["sub"]),))
    if not user or user.get("status") != "active":
        await ws.close(code=4401, reason="unauthorized")
        return
    await ws.accept()
    session = VoiceSession(ws, user)
    await session.run()

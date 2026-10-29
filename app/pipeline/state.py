# -*- coding: utf-8 -*-
"""حالة النماذج في الذاكرة (تحميل/جاهز/خطأ) — تُستخدم للعرض في الواجهة."""
from __future__ import annotations

import threading
import time
from typing import Any


class ModelState:
    def __init__(self, key: str, label: str):
        self.key = key
        self.label = label
        self.status = "idle"       # idle | loading | ready | error
        self.error: str | None = None
        self.detail: str | None = None
        self.loaded_at: float | None = None
        self.load_seconds: float | None = None
        self.lock = threading.Lock()

    def set(self, status: str, error: str | None = None, detail: str | None = None):
        self.status = status
        self.error = error
        if detail is not None:
            self.detail = detail

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "error": self.error,
            "detail": self.detail,
            "load_seconds": self.load_seconds,
        }


STATE: dict[str, ModelState] = {
    "asr": ModelState("asr", "الاستماع (Jais-ASR)"),
    "llm": ModelState("llm", "التفكير (Jais-3-7B)"),
    "tts": ModelState("tts", "الكلام (SILMA TTS)"),
}


def snapshot() -> dict:
    return {k: v.snapshot() for k, v in STATE.items()}


def all_ready() -> bool:
    return all(v.status == "ready" for v in STATE.values())


def mark_loading(key: str):
    STATE[key].set("loading")


def mark_ready(key: str, load_seconds: float | None = None):
    st = STATE[key]
    st.set("ready")
    st.loaded_at = time.time()
    if load_seconds is not None:
        st.load_seconds = round(load_seconds, 1)


def mark_error(key: str, error: str):
    STATE[key].set("error", error=str(error)[:500])

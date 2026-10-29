# -*- coding: utf-8 -*-
"""أدوات الصوت: تحويل PCM/WAV، إعادة التعيين، والقياسات."""
from __future__ import annotations

import io
import wave

import numpy as np


def pcm16_to_wav(pcm: bytes, sr: int) -> bytes:
    """إطار PCM16 خام → ملف WAV صالح للمتصفح."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm16(data: bytes) -> tuple[bytes, int]:
    """ملف WAV (أو أي صوت يدعمه soundfile) → PCM16 خام + معدل العينة."""
    with wave.open(io.BytesIO(data), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        import soundfile as sf

        arr, sr2 = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        pcm = float_to_pcm16(arr.mean(axis=1))
        return pcm, int(sr2)
    if ch > 1:
        arr = np.frombuffer(raw, dtype=np.int16).reshape(-1, ch).mean(axis=1)
        pcm = arr.astype(np.int16).tobytes()
    else:
        pcm = raw
    return pcm, sr


def float_to_pcm16(arr: np.ndarray) -> bytes:
    arr = np.asarray(arr, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    return (arr * 32767.0).astype(np.int16).tobytes()


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def resample_pcm16(pcm: bytes, src_sr: int, dst_sr: int) -> bytes:
    if src_sr == dst_sr:
        return pcm
    import soxr

    x = pcm16_to_float(pcm)
    y = soxr.resample(x, src_sr, dst_sr)
    return float_to_pcm16(y)


def rms(pcm: bytes) -> float:
    """جذر متوسط الطاقة — لكشف الكلام (VAD)."""
    if not pcm:
        return 0.0
    x = pcm16_to_float(pcm)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(x * x)))


def pcm_duration(pcm: bytes, sr: int) -> float:
    return (len(pcm) / 2) / float(sr) if sr else 0.0

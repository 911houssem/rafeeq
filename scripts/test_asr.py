# -*- coding: utf-8 -*-
"""اختبار نموذج الاستماع Jais-ASR — تحميل من الملفات الأصلية + تفريغ صوت عربي."""
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import asr as asr_mod  # noqa: E402
from app.pipeline.audio import wav_to_pcm16  # noqa: E402

wav_path = ROOT / "data" / "test_tts.wav"
if not wav_path.exists():
    print("لا يوجد ملف صوت للاختبار — شغّل test_tts.py أولًا")
    raise SystemExit(1)

t0 = time.time()
print("== تحميل نموذج Jais-ASR من الملفات الأصلية ==")
engine = asr_mod.get_asr()
print(f"== تم التحميل في {time.time()-t0:.1f}s ==")

pcm, sr = wav_to_pcm16(wav_path.read_bytes())
print(f"== الصوت: {(len(pcm)/2)/sr:.1f}s @ {sr}Hz — بدء التفريغ ==")
t1 = time.time()
res = engine.transcribe(pcm, sr)
dt = time.time() - t1
print(f"== التفريغ في {dt:.1f}s ==")
print("النص:", res["text"])
print("اللغة:", res.get("language"), "| مرفوض:", res.get("refused"))
print("OK")

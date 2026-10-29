# -*- coding: utf-8 -*-
"""اختبار محرك SILMA TTS من الملفات المحلية — تشغيل مباشر من سطر الأوامر."""
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import tts  # noqa: E402

t0 = time.time()
print("== تحميل نموذج SILMA من الملفات المحلية ==")
engine = tts.get_tts()
print(f"== تم التحميل في {time.time()-t0:.1f}s | device={engine.device} | sr={engine.target_sample_rate} ==")

text = "مرحبًا بك في نظام رفيق، أنا مساعدك الصوتي وأنا هنا لمساعدتك في كل ما تحتاجه."
t1 = time.time()
pcm, sr = engine.synthesize(text)
dt = time.time() - t1
dur = (len(pcm) / 2) / sr
print(f"== التوليد: {dt:.2f}s لصوت مدته {dur:.2f}s (RTF={dt/max(dur,0.01):.2f}) sr={sr} ==")

out = ROOT / "data" / "test_tts.wav"
from app.pipeline.audio import pcm16_to_wav  # noqa: E402

out.write_bytes(pcm16_to_wav(pcm, sr))
print(f"== حُفظ: {out} ==")

# اختبار المُطبِّع (بديل nemo)
from nemo_text_processing.text_normalization.normalize import Normalizer  # noqa: E402

n = Normalizer(lang="ar")
print("normalize:", n.normalize("سعره 25.5 دولار ووصلت الساعة 12:30 في 2026"))
print("OK")

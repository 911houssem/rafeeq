# -*- coding: utf-8 -*-
"""اختبار نموذج التفكير Jais-3-7B — تحميل من الملفات الأصلية + قياس السرعة."""
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.pipeline import llm as llm_mod  # noqa: E402

t0 = time.time()
print("== تحميل نموذج Jais-3-7B من الملفات الأصلية ==")
engine = llm_mod.get_llm()
print(f"== تم التحميل في {time.time()-t0:.1f}s ==")

msgs = [
    {"role": "system", "content": "أجب بإيجاز بالعربية."},
    {"role": "user", "content": "ما هي عاصمة المملكة العربية السعودية؟ أجب في جملة واحدة."},
]
t1 = time.time()
first = None
n = 0
chars = 0
print("== بدء التوليد ==")
for kind, piece in engine.stream(
    msgs, max_new_tokens=80, temperature=0.7, reasoning_effort="low"
):
    if kind == "content":
        if first is None:
            first = time.time() - t1
            print(f"أول حرف بعد: {first:.1f}s")
        n += 1
        chars += len(piece)
        print(piece, end="", flush=True)
total = time.time() - t1
print(f"\n== الإجمالي: {total:.1f}s | قطع={n} | أحرف={chars} | time-to-first={first}")
print("OK")

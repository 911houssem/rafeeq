# -*- coding: utf-8 -*-
"""
«رفيق» على Modal — النشر الكامل بصوت حقيقي (استماع + تفكير + نطق = 27.5GB معًا)
على كارت L40S 48GB باستخدام الرصيد المجاني المتجدد ($30/شهر) من Modal Starter — بلا بطاقة دفع.

التجهيز مرة واحدة على جهازك (3 دقائق):
    pip install modal
    modal setup          # يفتح المتصفح وتربط حسابك (اختر التسجيل عبر GitHub إذا أحببت)

النشر (من مجلد المشروع):
    modal run deploy/modal_app.py::download   # (مرة واحدة) يُنزّل النماذج الأصلية الثلاثة إلى وحدة تخزين دائمة
    modal deploy deploy/modal_app.py          # ينشر الخادم ويطبع رابطًا عموميًا دائمًا

ملاحظات:
- عند عدم استخدام أحد: الحاوية تتوقف تلقائيًا بعد 10 دقائق → استهلاك صفر.
- النماذج تبقى في Volume دائم (رفع مجاني حتى 1TB) — لا تنزيل متكرر.
- قاعدة البيانات (المستخدمون/الفوترة/المفاتيح) تبقى في Volume آخر دائم.
- L40S ≈ $0.00075/ثانية — الرصيد المجاني $30 يعطيك ~10-11 ساعة تشغيل شهريًا.
"""
import os

import modal

app = modal.App("rafeeq")

MODELS_VOL = modal.Volume.from_name("rafeeq-models", create_if_missing=True)
DATA_VOL = modal.Volume.from_name("rafeeq-data", create_if_missing=True)

MODELS_BASE = "/models"
RAFEEQ_ROOT = "/app/rafeeq"

ENV = {
    "RAFEEQ_MODEL_ASR_DIR": f"{MODELS_BASE}/asr",
    "RAFEEQ_MODEL_LLM_DIR": f"{MODELS_BASE}/llm",
    "RAFEEQ_MODEL_TTS_DIR": f"{MODELS_BASE}/tts",
    "RAFEEQ_DATA_DIR": "/data",
    "RAFEEQ_HOST": "0.0.0.0",
    "RAFEEQ_PORT": "8000",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
    "PIP_NO_CACHE_DIR": "1",
    "MPLBACKEND": "Agg",
    "HF_HOME": f"{MODELS_BASE}/hf",
}

# الصورة: أساس PyTorch/CUDA الرسمي + تنزيل الكود من GitHub عادةً (دائمًا آخر نسخة)
image = (
    modal.Image.from_registry("pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime", add_python="3.11")
    .apt_install("git", "libsndfile1")
    .run_commands(
        f"git clone --depth 1 https://github.com/911houssem/rafeeq {RAFEEQ_ROOT}",
        f"cd {RAFEEQ_ROOT} && python -m pip install --no-cache-dir -r deploy/requirements-server.txt",
        f"cd {RAFEEQ_ROOT} && python -m pip install --no-cache-dir --no-deps torchaudio==2.5.1 silma-tts",
    )
    .env(ENV)
)


@app.function(
    image=image,
    volumes={MODELS_BASE: MODELS_VOL, "/data": DATA_VOL},
    timeout=60 * 60,
    cpu=8,
    memory=32768,
)
def download():
    """(مرة واحدة) ينزّل النماذج الثلاثة الأصلية حرفيًا من HuggingFace إلى الوحدة الدائمة."""
    import subprocess

    env = dict(os.environ, RAFEEQ_MODELS_ROOT=MODELS_BASE)
    models = ["tts", "asr", "llm"]
    for key in models:
        cmd = ["python", f"{RAFEEQ_ROOT}/deploy/download_models.py", key]
        print("→", " ".join(cmd), flush=True)
        rc = subprocess.run(cmd, cwd=RAFEEQ_ROOT, env=env).returncode
        if rc != 0:
            raise RuntimeError(f"فشل تنزيل {key}")
    MODELS_VOL.commit()
    print("✅ النموذجات الثلاثة جاهزة في Volume دائمة — لن تُنزّل مرة أخرى", flush=True)


@app.function(
    image=image,
    gpu="L40S",
    volumes={MODELS_BASE: MODELS_VOL, "/data": DATA_VOL},
    timeout=60 * 60 * 4,
    scaledown_window=600,   # إيقاف تلقائي بعد 10 دقائق خمول = صفر تكلفة
    max_containers=1,
)
@modal.asgi_app()
def serve():
    # الجذر + ممرات الاستيراد
    os.chdir(RAFEEQ_ROOT)
    import sys

    sys.path.insert(0, RAFEEQ_ROOT)

    from app.main import app as rafeeq_app

    return rafeeq_app


if __name__ == "__main__":
    print("الاستخدام: modal run deploy/modal_app.py::download  ثم  modal deploy deploy/modal_app.py")

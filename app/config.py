# -*- coding: utf-8 -*-
"""الإعدادات الثابتة للنظام — المسارات والنماذج والمنافذ."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

# ---------------------------------------------------------------- المسارات
BASE_DIR = Path(__file__).resolve().parent.parent
# مجلد البيانات (قاعدة SQLite) قابل للتغيير عبر البيئة — للسحب نضعها في وحدة تخزين دائمة
DATA_DIR = Path(os.environ.get("RAFEEQ_DATA_DIR", str(BASE_DIR / "data")))
STATIC_DIR = BASE_DIR / "static"
DB_PATH = DATA_DIR / "app.db"
SECRET_PATH = DATA_DIR / "secret.key"
OFFLOAD_DIR = DATA_DIR / "offload"
VOICE_DIR = DATA_DIR / "voice"  # الصوت المرجعي لنظام TTS

# مجلدات النماذج الأصلية كما هي في الملفات (قابلة للتغيير عبر متغيرات البيئة للسيرفر)
MODEL_ASR_DIR = Path(os.environ.get("RAFEEQ_MODEL_ASR_DIR", str(BASE_DIR / "الاستماع Jais-ASR")))
MODEL_LLM_DIR = Path(os.environ.get("RAFEEQ_MODEL_LLM_DIR", str(BASE_DIR / "التفكير Jais 3 7B")))
MODEL_TTS_DIR = Path(os.environ.get("RAFEEQ_MODEL_TTS_DIR", str(BASE_DIR / "التحدث SILMA TTS")))

for _d in (DATA_DIR, OFFLOAD_DIR, VOICE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- الخادم
HOST = os.environ.get("RAFEEQ_HOST", "127.0.0.1")
PORT = int(os.environ.get("RAFEEQ_PORT", "8000"))

# ---------------------------------------------------------------- الصوت
CLIENT_PCM_RATE = 16000      # معدل إطارات المايك من المتصفح
TTS_RATE = 24000             # معدل SILMA الأصلي
FRAME_MS = 40                # طول الإطار الصوتي المرسل

# ---------------------------------------------------------------- النماذج
LLM_DTYPE = os.environ.get("RAFEEQ_LLM_DTYPE", "bfloat16")
ASR_DTYPE = os.environ.get("RAFEEQ_ASR_DTYPE", "bfloat16")
# في حال نقص الذاكرة: تُفعَّل التحميل مع الترحيل إلى القرص تلقائيًا
AUTO_OFFLOAD_ON_OOM = True

# ---------------------------------------------------------------- JWT
JWT_ALGO = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 24 * 7  # أسبوع


def get_secret() -> bytes:
    """مفتاح سري للتوقيع — يُنشأ تلقائيًا أول تشغيل ويُحفظ في data/secret.key"""
    if SECRET_PATH.exists():
        return SECRET_PATH.read_bytes()
    key = secrets.token_bytes(32)
    SECRET_PATH.write_bytes(key)
    try:
        os.chmod(SECRET_PATH, 0o600)
    except OSError:
        pass
    return key


# ---------------------------------------------------------------- الإعدادات الافتراضية
DEFAULT_SETTINGS: dict[str, str] = {
    "app_name": "رفيق",
    "assistant_name": "رفيق",
    "currency": "ر.س",
    # التسعير بالدقيقة (ليس بالتوكن)
    "price_per_minute": "0.50",            # سعر الدقيقة للمستخدم بدون اشتراك
    "free_minutes_signup": "30",           # رصيد مجاني عند التسجيل
    "allow_register": "1",
    # النص الإرشادي للنموذج
    "system_prompt_voice": (
        'أنت "رفيق"، مساعد صوتي عربي ودود تتحدث مع المستخدم كأنك إنسان حقيقي. '
        "قواعد المحادثة الصوتية:\n"
        "- أجب بإيجاز: جملتان إلى أربع جمل، بلغة عربية طبيعية مبسطة.\n"
        "- لا تستخدم جداول أو نقاط تعداد أو رموز تنسيق أو إيموجي.\n"
        "- تحدث مباشرة في الموضوع دون تكرار سؤال المستخدم.\n"
        "- إن سأل عن هويتك: قل إنك رفيق، مساعدك الصوتي المدعوم بنموذج جيس (Jais) "
        "من معهد النماذج التأسيسية والمركز الإماراتي للذكاء الاصطناعي.\n"
        '- تصرّف كإنسان حقيقي: ودود، مطمئن، وبسيط المزاح إن كان مناسبًا.'
    ),
    "system_prompt_text": (
        'أنت "رفيق"، مساعد ذكي عربي. أجب بدقة ووضوح، ويمكنك استخدام التنسيق '
        "المرتب (الجداول والنقاط) عند الحاجة. إن سأل عن هويتك فذكر أنك مدعوم "
        "بنموذج جيس (Jais)."
    ),
    # بارامترات النموذج اللغوي
    "llm_max_new_tokens_voice": "260",
    "llm_max_new_tokens_text": "1024",
    "llm_temperature": "0.7",
    "llm_top_p": "0.95",
    "llm_top_k": "20",
    "reasoning_effort_voice": "low",
    "reasoning_effort_text": "medium",
    # كشف نهاية الكلام
    "vad_silence_ms": "700",
    "vad_energy": "0.012",
    "vad_min_speech_ms": "250",
    # الفوترة (بالدقيقة)
    "min_billing_seconds": "30",
    # TTS
    "tts_speed": "1.0",
    "tts_reference_text": "",
    # التحميل المسبق للنماذج عند الإقلاع
    "warm_models": "1",
}

# الباقة المجانية الافتراضية وآخر الافتراضية
DEFAULT_PLANS = [
    # (name, price, minutes, description, sort)
    ("مجاني", 0.0, 30, "30 دقيقة مجانًا كل شهر — للمتجربين", 1),
    ("أساسي", 39.0, 300, "300 دقيقة شهريًا — للاستخدام الشخصي", 2),
    ("احترافي", 99.0, 1000, "1000 دقيقة شهريًا — للفريق والاستخدام المكثف", 3),
]

# حزم الشحن الإضافي (بالرصيد الدائم)
DEFAULT_TOPUPS = [
    # (amount price, minutes)
    (10.0, 20),
    (25.0, 55),
    (50.0, 120),
]

# 🚀 نشر «رفيق» على سيرفر سحابي بكارت شاشة

هذه الطريقة تُشغّل **نفس ملفاتك الأصلية حرفيًا** (bf16 الكاملة — بدون GGUF والنماذج موجودة رسميًا على HuggingFace) بسرعة كاملة: رد صوتي كامل في **~3-6 ثوانٍ** بدل دقائق/انفجار الذاكرة.

---

## 🆓 الاستضافة المجانية (بلا أي مبلغ)

### الفرع 1: GitHub Codespaces — واجهة + فوترة + مفاتيح API + نطق 🔊 (24/7 تقريبًا)
تعمل على حساب GitHub حرفيًا بلا أي دفع. الجهاز القياسي: 4 أنوية / 16GB رام.

```bash
gh auth refresh -s codespace     # تفويض مرة واحدة
gh codespace create --repo 911houssem/rafeeq --branch main \
  --machine standardLinux32gb --idle-timeout 240m
# داخل المساحة: bash /workspaces/rafeeq/deploy/codespace.sh
# ثم اجعل المنفذ 8000 عامًا: gh codespace ports visibility 8000:public -c <اسم-المساحة>
```
النطق الخارج (`/api/tts` + زر 🔊) يعمل؛ الميكروفون يحتاج كارت شاشة (48GB — انظر الفرع 2).

### الفرع 2: Modal — الصوت الكامل (كارت L40S 48GB) برصيد مجاني متجدد $30/شهر
```bash
pip install modal && modal setup
modal run deploy/modal_app.py::download     # مرة واحدة: تنزيل النماذج الأصلية
modal deploy deploy/modal_app.py            # رابط عمومي فوري
```
الأصلية 100% (بلا GGUF)، وإيقاف تلقائي عند الخمول = صفر استهلاك. ضمن الرصيد المجاني: ~10-11 ساعة تشغيل شهريًا.

---

## ⚡ الخيار الأول: RunPod (الأسهل والأسرع — موصى به)

**التكلفة:** كارت 48GB مثل L40S أو A6000 ≈ **0.5–0.8$/ساعة** (شغّله فقط عندما تريد — أوقفه وينقطع الفاتورة).

1. افتح [runpod.io](https://www.runpod.io/) → أنشئ حساب → **Pods → Deploy**
2. اختر GPU: **RTX 4090 (24GB)** للنص/الـAPI فقط، أو **L40S / A6000 (48GB)** للتجربة الصوتية الكاملة (الصوت يحتاج نموذجين مقيمين معًا = 27.5GB)
   - Disk: **60GB** النمط "Container Disk" أو "Volume" — والتجربة ممكنة بـ"Community Cloud" الأرخص
3. Template: اختر قالب **PyTorch 2.5.1 / CUDA 12.4** جاهز من RunPod (أو أي قالب Ubuntu + CUDA)
4. بعد إقلاع الـPod افتح **Web Terminal** والصق السطر التالي (يُنزّل المشروع والنماذج ويشغّل):

```bash
apt-get update -y && apt-get install -y git python3.11 python3.11-venv >/dev/null 2>&1;
git clone https://github.com/911houssem/rafeeq /app 2>/dev/null; cd /app;
python3.11 -m venv .venv && source .venv/bin/activate &&
pip install -q -r deploy/requirements-server.txt &&
python deploy/download_models.py && mkdir -p data &&
RAFEEQ_HOST=0.0.0.0 RAFEEQ_MODEL_ASR_DIR=/app/models/asr \
RAFEEQ_MODEL_LLM_DIR=/app/models/llm RAFEEQ_MODEL_TTS_DIR=/app/models/tts \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> تنزيل النماذج ~27GB يشته من مركز البيانات بسرعة عالية (~5–15 دقيقة أول مرة فقط). اضبط مسار المودلز في `/app/models` أو حدد `RAFEEQ_MODELS_ROOT` عبر `python deploy/download_models.py` مع `RAFEEQ_MODELS_ROOT=/app/models`.

5. من إعدادات الـPod فعّل تعرّض المنفذ **8000 (HTTP)** — ستحصل على رابط عمومي مثل:
   `https://xxxxx-8000.proxy.runpod.net`
6. افتح الرابط → أنشئ حساب المالك → **النظام يعمل الآن بصوته الكامل** 🎉

### ✅ نصائح مهمة على RunPod
- عند إيقاف الـPod لا تُحذف النماذج إن حفظتها في **Volume** (وليس Container Disk) — أوقف/شغّل وتشغّل الأمر من جديد (النماذج موجودة، سيتخطى التنزيل).
- للإنتاج insomnia: اشترِ **Dedicated GPU** (بلا حصة مجانية غياب مفاجئ).
- ضع `HF_TOKEN` لو حصل rate-limit أثناء التنزيل (اختياري تمامًا).

---

## 🖥️ الخيار الثاني: VPS كامل بـ Docker (Hetzner GPU أو أي مزود)

1. سيرفر Ubuntu 22.04 مع NVIDIA + تثبيت [docker](https://docs.docker.com/) و[compose](https://docs.docker.com/compose/) و`nvidia-container-toolkit`
2. على جهازك:
```bash
git clone https://github.com/911houssem/rafeeq && cd rafeeq/deploy
docker compose up -d      # يحبّ الصورة ويشغّل الخادم
docker compose exec rafeeq python deploy/download_models.py   # ينزّل النماذج إلى ./models
docker compose restart
```
3. افتح `http://IP-السيرفر:8000` (ضع HTTPS لاحقًا عبر Nginx/Caddy + دومين).

---

## ⚙️ إعدادات مهمة بعد أول تشغيل (داخل لوحة المالك)
- **warm_models = 1** لتحميل النماذج تلقائيًا عند الإقلاع.
- تأكد من `RAFEEQ_HOST=0.0.0.0` ليستقبل من الإنترنت (الافتراضي في Docker محدد).
- أدخل من أول زيارة وأنشئ **حساب المالك** فورًا (بعد ذلك تُغلق هذه الشاشة للأبد).
- الفوترة والدقائق تعمل كما في جهازك — قاعدة البيانات في `data/app.db` (احفظها أو اتصل بـPostgreSQL لاحقًا).

---

## 💰 حساب سريع لمشروعك التجاري (مثلًا)
- L40S = ~0.55$/ساعة = **480$/شهر إذا شغّلته 24/7** — أو أكثر واقعية: تفعّه فقط في أوقات الذروة (12 ساعة يوميًا ≈ 200$/شهر).
- سعر الدقيقة عندك 0.5 ر.س → أي 960 دقيقة مستخدم/شهر = 480 ر.س (~130$) يغطي السيرفر — **وحسّن هامش ربحك بإيقاف Pod في الأوقات الفارغة**.
- للتوسع: نفس الصورة تعمل على أي كارت أكبر بدون أي تعديل، ويمكن رفع سعر باقة «احترافي» من لوحة المالك بنقرة.

---

## 📌 ملاحظة مهمة لقرارك الأصلي
هذه الطريقة **لا تلمس قرارك أبدًا** — تشغيل فعلي للملفات الأصلية bf16 الكاملة، منسوخة من نفس المستودعات الرسمية الذي جاءت منها ملفاتك
(`inception42/Jais-3-7B` + `IFM/Jais-ASR` + `silma-ai/silma-tts`) — **بلا GGUF وبلا أي ضغط أو تعديل**.

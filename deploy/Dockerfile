# رفيق — صورة الكل الرسمان
# أساس PyTorch الرسمي مع CUDA (النماذج تعمل bf16 على كرت الشاشة تلقائيًا)
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# كود التطبيق (المستودع) — مجلدات النماذج تنزّل لاحقًا على الفوليوم
COPY requirements.txt deploy/requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt

COPY app ./app
COPY vendor ./vendor
COPY static ./static
COPY scripts ./scripts

# مجلد النماذج (يُملأ بـ deploy/download_models.py أو رفع يدوي)
ENV RAFEEQ_MODEL_ASR_DIR=/models/asr \
    RAFEEQ_MODEL_LLM_DIR=/models/llm \
    RAFEEQ_MODEL_TTS_DIR=/models/tts \
    RAFEEQ_HOST=0.0.0.0 \
    RAFEEQ_PORT=8000

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]

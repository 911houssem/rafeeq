#!/usr/bin/env bash
# ============================================================
# رفيق — تجهيز ونشر آلي في GitHub Codespaces (بدون كارت شاشة)
# يعمل على الخادم المجاني: الواجهة + الحسابات + الفوترة بالدقيقة + مفاتيح API + الصوت الخارج (SILMA TTS)
# لا يعمل على هذا الجهاز: الاستماع من الميكروفون (Jais-ASR يحتاج كارت شاشة) — النماذج الثلاثة معًا تحتاج 48GB
#
# الاستخدام:
#   bash /workspaces/rafeeq/deploy/codespace.sh
# لإضافة نموذج التفكير أيضًا (إن وُجدت الموارد):
#   RAFEEQ_CODESPACE_LLM=1 bash /workspaces/rafeeq/deploy/codespace.sh
# ============================================================
set -uo pipefail
cd /workspaces/rafeeq || { echo "❌ المستودع غير موجود في /workspaces/rafeeq"; exit 1; }
export PYTHONIOENCODING=utf-8 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg
log(){ echo "[$(date +%H:%M:%S)] $*"; }

PY=python3; command -v python3 >/dev/null 2>&1 || PY=python
log "الموارد: عدد الأنوية=$(nproc) | RAM=$(free -g | awk 'NR==2{print $2}')GB | قرص متاح=$(df -h /workspaces | awk 'NR==2{print $4}')"
log "1/4 بايثون: $($PY -V 2>&1)"

# مكتبة النظام المطلوبة لقراءة الصوت
sudo apt-get install -y -qq libsndfile1 >/dev/null 2>&1 || true

pinstall(){ $PY -m pip install -q "$@" || $PY -m pip install -q --break-system-packages "$@"; }

log "2/4 تثبيت المكتبات (torch بمعمارية CPU)"
pinstall --upgrade pip
pinstall torch torchaudio --index-url https://download.pytorch.org/whl/cpu
grep -v '^onnxruntime-gpu' deploy/requirements-server.txt > /tmp/rafeeq-req.txt
echo 'onnxruntime' >> /tmp/rafeeq-req.txt
pinstall -r /tmp/rafeeq-req.txt
pinstall --no-deps silma-tts

log "3/4 تنزيل النماذج الأصلية المطلوبة (نفس ملفاتك حرفيًا — بلا GGUF)"
TARGETS="tts"
[ "${RAFEEQ_CODESPACE_LLM:-0}" = "1" ] && TARGETS="$TARGETS llm"
RAFEEQ_MODELS_ROOT=/workspaces/rafeeq/models $PY deploy/download_models.py $TARGETS

LLM_DIR="/workspaces/rafeeq/models-llm-missing"
[ -f "/workspaces/rafeeq/models/llm/config.json" ] && LLM_DIR="/workspaces/rafeeq/models/llm"

log "4/4 تشغيل الخادم على المنفذ 8000"
mkdir -p data
if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  log "الخادم يعمل أصلًا — لا شيء لأفعله"
else
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  RAFEEQ_HOST=0.0.0.0 RAFEEQ_PORT=8000 \
    RAFEEQ_MODEL_TTS_DIR="/workspaces/rafeeq/models/tts" \
    RAFEEQ_MODEL_ASR_DIR="/workspaces/rafeeq/models-asr-missing" \
    RAFEEQ_MODEL_LLM_DIR="$LLM_DIR" \
    nohup $PY -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
  log "بدأ التشغيل — السجل: /workspaces/rafeeq/server.log"
fi
log "انتهى — افحص http://127.0.0.1:8000/api/health"

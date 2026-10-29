#!/usr/bin/env bash
# ============================================================
# «رفيق» — فتح رابط عمومي مجاني فوري داخل Codespaces
# يعمل بلا حساب: نفق cloudflared سريع (trycloudflare.com)
# الاستخدام: bash deploy/tunnel.sh
# إغلاق النفق: pkill -f "cloudflared tunnel"
# ============================================================
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BIN=/tmp/cloudflared
URL=""

if [ ! -x "$BIN" ]; then
  echo "… تحميل cloudflared (مرة واحدة)…"
  curl -fsSL -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 || exit 1
  chmod +x "$BIN"
fi

pkill -f "cloudflared tunnel" 2>/dev/null || true
echo "… فتح النفق إلى 127.0.0.1:8000 …"
setsid nohup "$BIN" tunnel --url http://127.0.0.1:8000 --no-autoupdate > tunnel.log 2>&1 < /dev/null &

for i in $(seq 1 45); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' tunnel.log 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 2
done

if [ -n "$URL" ]; then
  echo "PUBLIC_URL=$URL"
else
  echo "تعذر الحصول على الرابط — راجع tunnel.log في مجلد المستودع"
  tail -8 tunnel.log
fi

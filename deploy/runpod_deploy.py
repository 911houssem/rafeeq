# -*- coding: utf-8 -*-
"""
النشر الآلي لـ«رفيق» على RunPod — من مفتاح API وحتى رابط يعمل.
  Usage:
    python deploy/runpod_deploy.py --key rp_XXXX            # إنشاء وإقلاع وانتظار الجاهزية
    python deploy/runpod_deploy.py --key rp_XXXX --gpu "NVIDIA L40S"
    python deploy/runpod_deploy.py --key rp_XXXX --stop pod_id   # إيقاف (توفير المال)
    python deploy/runpod_deploy.py --key rp_XXXX --status pod_id # حالة بحث
المطلوب مسبقًا: حساب RunPod + رصيد (~10$) + API Key من Settings → API Keys
"""
import argparse
import json
import sys
import time
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API = "https://api.runpod.io/graphql"

# ترتيب تفضيل الكروت (أكبر ذاكرة أولًا — للصوت الكامل نحتاج 48GB)
GPU_PREFERENCE = [
    "NVIDIA L40S", "NVIDIA A6000", "NVIDIA RTX A6000",
    "NVIDIA L40", "NVIDIA H100", "NVIDIA H200",
    "NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 4090 (Beta)",
]

# أمر التجهيز الكامل داخل الـPod: نسخ المستودع + المكتبات + النماذج الأصلية + تشغيل الخادم
SETUP_CMD = (
    "bash -lc 'set -e; "
    "export DEBIAN_FRONTEND=noninteractive; "
    "apt-get update -y >/dev/null 2>&1; apt-get install -y git >/dev/null 2>&1 || true; "
    "python -V; "
    "pip install -q --upgrade pip; "
    "if [ ! -d /workspace/rafeeq ]; then git clone --depth 1 https://github.com/911houssem/rafeeq /workspace/rafeeq; fi; "
    "cd /workspace/rafeeq; "
    "pip install -q -r deploy/requirements-server.txt; "
    "mkdir -p /workspace/models data; "
    "python deploy/download_models.py; "
    "RAFEEQ_HOST=0.0.0.0 RAFEEQ_PORT=8000 "
    "RAFEEQ_MODEL_ASR_DIR=/workspace/models/asr "
    "RAFEEQ_MODEL_LLM_DIR=/workspace/models/llm "
    "RAFEEQ_MODEL_TTS_DIR=/workspace/models/tts "
    "nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /workspace/rafeeq.log 2>&1 & "
    "sleep 360000'"
)


def gql(api_key: str, query: str, variables: dict | None = None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(
        API + "?api_key=" + api_key,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"خطأ HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
    if data.get("errors"):
        raise SystemExit("خطأ GraphQL: " + json.dumps(data["errors"], ensure_ascii=False)[:800])
    return data["data"]


def pick_gpu(api_key: str, want: str | None) -> str:
    data = gql(api_key, "query { gpuTypes { id displayName memoryInGb lowestPrice { unavailable } } }")
    for t in data["gpuTypes"]:
        if want and (want.lower() in t["id"].lower() or want.lower() in (t.get("displayName") or "").lower()):
            return t["id"]
    for pref in GPU_PREFERENCE:
        for t in data["gpuTypes"]:
            if pref.lower() in t["id"].lower() and not (t["lowestPrice"] or {}).get("unavailable"):
                print(f"ث اختيار الكارت: {t['displayName']} ({t['memoryInGb']}GB)")
                return t["id"]
    raise SystemExit("لاوجد كارت متاح من قائمة الأفضلية — حدد --gpu")


def create_pod(api_key: str, gpu_want: str | None) -> str:
    gpu_id = pick_gpu(api_key, gpu_want)
    print("… إنشاء Pod على", gpu_id)
    m = gql(
        api_key,
        """
        mutation ($in: PodPodInput!) {
          savePod(input: $in) { id desiredStatus }
        }
        """,
        {
            "in": {
                "cloudType": "SECURE",
                "name": "rafeeq",
                "gpuTypeId": gpu_id,
                "gpuCount": 1,
                "volumeInGb": 60,
                "containerDiskInGb": 30,
                "volumeMountPath": "/workspace",
                "ports": "8000/http",
                "publicIpType": "shared",
                "startOnLaunch": True,
                "imageName": "runpod/pytorch:2.5.1-py3.11-cuda12.4.1-ubuntu22.04",
                "dockerArgs": SETUP_CMD,
                "minVcpuCount": 8,
                "minMemoryInGb": 32,
                "supportPublicIp": True,
                "env": [
                    {"key": "RAFEEQ_HOST", "value": "0.0.0.0"},
                    {"key": "HF_HOME", "value": "/workspace/hf"},
                ],
            }
        },
    )
    pod = m["savePod"]
    print("✅ أُنشئ Pod بمعرّف:", pod["id"])
    return pod["id"]


def get_pod(api_key: str, pod_id: str) -> dict:
    m = gql(
        api_key,
        """
        query ($id: String!) {
          pod(input: {podId: $id}) {
            id desiredStatus imageName gpuIds
            runtime {
              uptimeSeconds
              ports { ip isIpPublic privatePort publicPort type }
            }
          }
        }
        """,
        {"id": pod_id},
    )
    return m["pod"]


def public_url(api_key: str, pod_id: str) -> str | None:
    pod = get_pod(api_key, pod_id)
    rt = pod.get("runtime") or {}
    for p in rt.get("ports", []):
        if p.get("type") == "http" and p.get("publicPort"):
            host = p.get("ip") or f"{pod_id}-{p['publicPort']}.proxy.runpod.net"
            if not p.get("isIpPublic"):
                host = f"{pod_id}-{p['publicPort']}.proxy.runpod.net"
            return f"https://{host}:{p['publicPort']}"
    return None


def wait_ready(api_key: str, pod_id: str, minutes: int = 50):
    """انتظار حتى يستجيب /api/health (تنزيل النماذج يأخذ ~10-20 دقيقة أول مرة)."""
    print("⏳ انتظار جاهزية النظام (النموذز تُنزّل تلقائيًا داخل السيرفر)…")
    t0 = time.time()
    while time.time() - t0 < minutes * 60:
        pod = get_pod(api_key, pod_id)
        status = pod.get("desiredStatus")
        if status.lower() in ("exited", "failed"):
            raise SystemExit("❌ الـPod توقفت — افتح وحدة تحكم RunPod لتشاهد السجل.")
        url = public_url(api_key, pod_id)
        if url:
            try:
                with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=10) as r:
                    print("✅ السيرفر يستجيب!", r.read().decode()[:200])
                    print("\n🌐 الرابط العمومي:", url)
                    print("→ افتحه الآن وأنشئ حساب المالك (مرة واحدة فقط).")
                    return url
            except Exception as e:  # noqa: BLE001
                elapsed = int(time.time() - t0)
                print(f"   … {elapsed//60}د{elapsed%60:02d}ث — التجهيز مستمر ({type(e).__name__})")
        time.sleep(45)
    raise SystemExit("انتهى زمن الانتظار — راجع سجل RunPod ثم استخدم --status")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--gpu", default=None)
    ap.add_argument("--stop", metavar="POD_ID")
    ap.add_argument("--status", metavar="POD_ID")
    ap.add_argument("--resume", metavar="POD_ID", help="متابعة انتظار Pod قائم")
    args = ap.parse_args()

    if args.stop:
        gql(args.api_key if hasattr(args, "api_key") else args.key,
            'mutation ($id: String!) { podTerminate(input: {podId: $id}) }', {"id": args.stop})
        print("🛑 أُرسل أمر الإيقاف — الفاتورة تتوقف تقريبًا فورًا")
        return
    if args.status:
        pod = get_pod(args.key, args.status)
        url = public_url(args.key, args.status)
        print(json.dumps(pod, ensure_ascii=False, indent=2)[:1200])
        print("الرابط:", url)
        return

    pod_id = args.resume or create_pod(args.key, args.gpu)
    wait_ready(args.key, pod_id)


if __name__ == "__main__":
    main()

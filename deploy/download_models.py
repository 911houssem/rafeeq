# -*- coding: utf-8 -*-
"""
تنزيل النماذج الثلاثة الأصلية إلى السيرفر (نفس ملفات جهازك حرفيًا — نفس الريبوهات الرسمية):
 _PROVIDER/ endothelium... 
Usage:
  python deploy/download_models.py            # الثلاثة
  python deploy/download_models.py llm tts    # جزئيًا
متغيرات البيئة (اختيارية):
  RAFEEQ_MDOELS_ROOT=/models
  HF_TOKEN=hf_...   (لو احتاج ريبو موافقة)
"""
import os
import shutil
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from huggingface_hub import snapshot_download

REPOS = {
    "asr": ("IFM/Jais-ASR", "asr"),
    "llm": ("inception42/Jais-3-7B", "llm"),
    "tts": ("silma-ai/silma-tts", "tts"),
}
ROOT = Path(os.environ.get("RAFEEQ_MODELS_ROOT", "/models"))


def disk_gb_free(path: Path) -> float:
    usage = shutil.disk_usage(str(path))
    return usage.free / 1e9


def download(keys):
    ROOT.mkdir(parents=True, exist_ok=True)
    need = {"asr": 12, "llm": 18, "tts": 3}
    free = disk_gb_free(ROOT)
    total = sum(need[k] for k in keys)
    if free < total:
        print(f"⚠️ تحذير: مساحة القرص المتاحة {free:.1f}GB بينما تحتاج {total}GB تقريبًا")
    token = os.environ.get("HF_TOKEN")
    for k in keys:
        repo, folder = REPOS[k]
        dest = ROOT / folder
        print(f"== [{k}] تنزيل {repo} → {dest} ==")
        snapshot_download(
            repo_id=repo,
            local_dir=str(dest),
            token=token,
            max_workers=8,
        )
        size = sum(f.stat().st_size for f in dest.rglob("*") if f.is_file()) / 1e9
        print(f"✅ [{k}] اكتمل — {size:.1f}GB في {dest}")
    print("جاهز — شغّل الخادم: uvicorn app.main:app --host 0.0.0.0 --port 8000")


if __name__ == "__main__":
    keys = [a for a in sys.argv[1:] if a in REPOS] or list(REPOS)
    download(keys)

# -*- coding: utf-8 -*-
"""تقسيم النص المتدفق إلى جُمل لتشغيل النطق أولًا بأول (بلا انتظار الرد الكامل)."""
from __future__ import annotations

import re

# علامات الانتهاء القوية
_STRONG = ".!؟?…\n"
# علامات ضعيفة (تفصل عند طول كافٍ فقط)
_WEAK = "،,:؛;"

_TAG_HOLD = 24  # احتياطي للعلامات الطويلة


class SentenceStreamer:
    """
    يُغذّي النص المتدفق قطعةً قطعة، ويُعيد الجُمل المكتملة فورًا.
    الهدف: أسرع بدء للنطق (أول جملة تُنطق والنموذج ما زال يكتب).
    """

    def __init__(self, max_chars: int = 240, min_emit: int = 12):
        self.buf = ""
        self.max_chars = max_chars
        self.min_emit = min_emit

    def feed(self, piece: str) -> list[str]:
        if not piece:
            return []
        self.buf += piece
        out: list[str] = []
        while True:
            idx = self._find_split()
            if idx is None:
                break
            sent = self.buf[: idx + 1].strip()
            self.buf = self.buf[idx + 1 :]
            if sent:
                out.append(sent)
        # طول زائد بدون علامات: اقتصّ عند آخر مسافة
        if len(self.buf) > self.max_chars:
            sp = self.buf.rfind(" ", 0, self.max_chars)
            if sp > self.min_emit:
                out.append(self.buf[:sp].strip())
                self.buf = self.buf[sp + 1 :]
        return out

    def flush(self) -> list[str]:
        rest = self.buf.strip()
        self.buf = ""
        return [rest] if rest else []

    def _find_split(self) -> int | None:
        s = self.buf
        for i, ch in enumerate(s):
            if ch in _STRONG:
                # تجاهل النقاط داخل الأرقام (3.5) أو الاختصارات
                if ch == "." and i > 0 and i + 1 < len(s):
                    if s[i - 1].isdigit() and s[i + 1].isdigit():
                        continue
                if i + 1 < self.min_emit and len(s) < self.max_chars:
                    continue
                return i
            if ch in _WEAK and i >= 60:
                return i
        return None


def clean_for_speech(text: str) -> str:
    """تنظيف الرد من تنسيق Markdown قبل النطق (جداول، رموز، إيموجي...)."""
    t = text
    t = re.sub(r"```.*?```", " ", t, flags=re.S)          # كود
    t = re.sub(r"`([^`]*)`", r"\1", t)                     # inline code
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)            # صور
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)         # روابط
    t = re.sub(r"^\s*\|.*\|\s*$", " ", t, flags=re.M)      # صفوف جداول
    t = re.sub(r"^\s*[-*+]\s+", "", t, flags=re.M)         # نقط مسفلة
    t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.M)         # نقط مرقّمة
    t = re.sub(r"[#*_~]{1,3}", "", t)                      # علامات تأكيد
    t = re.sub(r"\s+", " ", t)
    return t.strip()

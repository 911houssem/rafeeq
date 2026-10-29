# -*- coding: utf-8 -*-
"""مُطبِّع نصوص خفيف (يعوض NeMo Text Processing على ويندوز)."""
from __future__ import annotations

import re

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_EN_ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
_EN_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_AR_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
_AR_TEENS = ["عشرة", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر",
             "ستة عشر", "سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_AR_TENS = ["", "", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_AR_HUNDREDS = ["", "مئة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة",
                "ستمائة", "سبعمائة", "ثمانمائة", "تسعمائة"]


def _en_int(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _EN_TENS[t] + ("-" + _EN_ONES[o] if o else "")
    if n < 1000:
        h, r = divmod(n, 100)
        return _EN_ONES[h] + " hundred" + (" " + _en_int(r) if r else "")
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        return _en_int(th) + " thousand" + (" " + _en_int(r) if r else "")
    return str(n)


def _ar_int(n: int) -> str:
    if n == 0:
        return "صفر"
    if n < 10:
        return _AR_ONES[n]
    if n < 20:
        return _AR_TEENS[n - 10]
    if n < 100:
        t, o = divmod(n, 10)
        if o == 0:
            return _AR_TENS[t]
        return _AR_ONES[o] + " و" + _AR_TENS[t]
    if n < 1000:
        h, r = divmod(n, 100)
        if r == 0:
            return _AR_HUNDREDS[h]
        return _AR_HUNDREDS[h] + " و" + _ar_int(r)
    if n < 1_000_000:
        th, r = divmod(n, 1000)
        if th == 1:
            head = "ألف"
        elif th == 2:
            head = "ألفان"
        elif th <= 10:
            head = _ar_int(th) + " آلاف"
        else:
            head = _ar_int(th) + " ألف"
        if r == 0:
            return head
        return head + " و" + _ar_int(r)
    return str(n)


class Normalizer:
    """واجهة متوافقة مع NeMo Normalizer المستخدمة داخل SILMA TTS."""

    def __init__(self, input_case: str = "cased", lang: str = "en", **kwargs):
        self.lang = "ar" if str(lang).startswith("ar") else "en"

    def _expand(self, m: re.Match) -> str:
        raw = m.group(0)
        try:
            if "." in raw:
                int_part, frac = raw.split(".", 1)
                n = int(int_part)
                sep = " فاصلة " if self.lang == "ar" else " point "
                words = [_ar_int(n) if self.lang == "ar" else _en_int(n)]
                words.append(sep.strip())
                for d in frac:
                    if d.isdigit():
                        words.append(
                            (_AR_ONES[int(d)] if self.lang == "ar" else _EN_ONES[int(d)])
                        )
                return " ".join(words)
            n = int(raw)
            if n > 999_999_999:
                return raw
            return _ar_int(n) if self.lang == "ar" else _en_int(n)
        except Exception:
            return raw

    def normalize(
        self,
        text: str,
        verbose: bool = False,
        punct_pre_process: bool = True,
        punct_post_process: bool = True,
        **kwargs,
    ) -> str:
        if not text:
            return text
        t = text.translate(_AR_DIGITS)
        # النسبة المئوية
        t = re.sub(r"(\d+)\s*%", lambda m: (self._expand(m) + (" بالمئة" if self.lang == "ar" else " percent")), t)
        # الأعداد العشرية والصحيحة
        t = re.sub(r"\d+(?:\.\d+)?", self._expand, t)
        if punct_post_process:
            t = re.sub(r"\s+", " ", t)
            t = re.sub(r"\s+([،,.!?:;؟])", r"\1", t)
            t = re.sub(r"([،,.!?:;؟])(?=\S)", r"\1 ", t)
            t = t.strip()
        return t

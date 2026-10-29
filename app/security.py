# -*- coding: utf-8 -*-
"""الأمان: كلمات المرور، JWT، مفاتيح API، والأدوار والصلاحيات."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Optional

from . import config

# ---------------------------------------------------------------- الأدوار والصلاحيات
PERMISSIONS = {
    "chat.use": "استخدام المحادثة النصية والصوتية",
    "keys.manage": "إدارة مفاتيح API الخاصة",
    "billing.view": "عرض الفواتير والرصيد الخاص",
    "billing.topup": "شحن رصيد الدقائق",
    "users.manage": "إدارة المستخدمين والصلاحيات",
    "plans.manage": "إدارة الباقات والاشتراكات",
    "keys.admin": "عرض وإلغاء مفاتيح API لجميع المستخدمين",
    "stats.view": "عرض لوحة الإحصائيات",
    "settings.manage": "تعديل إعدادات النظام والتسعير",
    "audit.view": "عرض سجل التدقيق",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    # المالك: كل الصلاحيات دون استثناء
    "owner": set(PERMISSIONS.keys()),
    # المشرف: إدارة التشغيل دون لمس إعدادات النظام الحساسة
    "admin": {
        "chat.use",
        "keys.manage",
        "billing.view",
        "users.manage",
        "plans.manage",
        "keys.admin",
        "stats.view",
        "audit.view",
    },
    # المستخدم العادي
    "user": {"chat.use", "keys.manage", "billing.view", "billing.topup"},
}

ROLE_LABELS = {"owner": "المالك", "admin": "مشرف", "user": "مستخدم"}


def can(role: str, perm: str) -> bool:
    return perm in ROLE_PERMISSIONS.get(role, set())


def perms_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, set()))


# ---------------------------------------------------------------- كلمات المرور
_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expect = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(rounds)
        )
        return hmac.compare_digest(dk, expect)
    except Exception:
        return False


# ---------------------------------------------------------------- JWT
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: int, role: str, minutes: int | None = None) -> str:
    header = {"alg": config.JWT_ALGO, "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "role": role,
        "exp": int(time.time()) + (minutes or config.ACCESS_TOKEN_MINUTES) * 60,
        "iat": int(time.time()),
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(config.get_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def decode_token(token: str) -> Optional[dict]:
    try:
        h, p, sig = token.split(".")
        expect = hmac.new(config.get_secret(), f"{h}.{p}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expect, _b64url_decode(sig)):
            return None
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ---------------------------------------------------------------- مفاتيح API
API_KEY_RE = re.compile(r"^sk-[A-Za-z0-9_\-]{16,}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def generate_api_key() -> tuple[str, str, str]:
    """يعيد (المفتاح الكامل، البادئة للعرض، الهاش للتخزين)."""
    full = "sk-" + secrets.token_urlsafe(32)
    prefix = full[:15] + "…"
    return full, prefix, hash_api_key(full)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def valid_password(pw: str) -> bool:
    return isinstance(pw, str) and len(pw) >= 6

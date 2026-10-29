# -*- coding: utf-8 -*-
"""اعتمادات FastAPI: المستخدم الحالي، الصلاحيات، ومفاتيح API."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .. import db, security


def _bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    # دعم ?token= للـ WebSocket والإطارات
    q = request.query_params.get("token")
    return q or None


def user_from_api_key(key: str) -> dict | None:
    if not security.API_KEY_RE.match(key):
        return None
    h = security.hash_api_key(key)
    row = db.one(
        "SELECT k.id AS kid, k.user_id, u.* FROM api_keys k JOIN users u ON u.id=k.user_id "
        "WHERE k.key_hash=? AND k.revoked_at IS NULL",
        (h,),
    )
    if not row:
        return None
    if row.get("status") != "active":
        return None
    db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (db.now_iso(), row["kid"]))
    return row


async def get_user(request: Request) -> dict:
    """يُعيد المستخدم النشط — عبر JWT أو مفتاح API (sk-...)."""
    token = _bearer(request)
    if not token:
        raise HTTPException(status_code=401, detail="غير مصرّح — سجّل الدخول أولًا")
    if token.startswith("sk-"):
        user = user_from_api_key(token)
        if not user:
            raise HTTPException(status_code=401, detail="مفتاح API غير صالح أو ملغى")
        return user
    payload = security.decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة — سجّل الدخول مجددًا")
    user = db.one("SELECT * FROM users WHERE id=?", (int(payload["sub"]),))
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="الحساب موقوف — تواصل مع المالك")
    return user


def require(perm: str):
    """مُعامل يتحقق من صلاحية محددة (owner يملك كل الصلاحيات)."""

    async def dep(user: dict = Depends(get_user)) -> dict:
        if not security.can(user.get("role", "user"), perm):
            raise HTTPException(
                status_code=403,
                detail=f"ليست لديك صلاحية: {security.PERMISSIONS.get(perm, perm)}",
            )
        return user

    return dep


def is_staff(user: dict) -> bool:
    return user.get("role") in ("owner", "admin")


def is_owner(user: dict) -> bool:
    return user.get("role") == "owner"


def public_user(user: dict) -> dict:
    """صورة المستخدم للواجهة (بدون بيانات حساسة)."""
    return {
        "id": user["id"],
        "email": user.get("email"),
        "display_name": user.get("display_name") or user.get("username") or "",
        "role": user.get("role"),
        "role_label": security.ROLE_LABELS.get(user.get("role", "user"), user.get("role")),
        "perms": security.perms_for(user.get("role", "user")),
        "created_at": user.get("created_at"),
        "minutes": db.user_minutes_state(user),
        "free": is_staff(user),  # المالك والمشرف بلا فوترة
    }

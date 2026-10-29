# -*- coding: utf-8 -*-
"""إدارة مفاتيح API (sk-...) — إنشاء، عرض، إلغاء."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import db, security
from .deps import get_user, require

router = APIRouter(prefix="/api/keys", tags=["keys"])


class KeyIn(BaseModel):
    name: str = Field(default="مفتاح جديد", max_length=80)


@router.get("")
def list_keys(user: dict = Depends(require("keys.manage"))):
    rows = db.query(
        "SELECT id, name, key_prefix, created_at, last_used_at, revoked_at "
        "FROM api_keys WHERE user_id=? ORDER BY id DESC",
        (user["id"],),
    )
    return {"keys": rows}


@router.post("")
def create_key(body: KeyIn, user: dict = Depends(require("keys.manage"))):
    full, prefix, khash = security.generate_api_key()
    kid = db.execute(
        "INSERT INTO api_keys(user_id,name,key_hash,key_prefix,created_at) VALUES(?,?,?,?,?)",
        (user["id"], body.name.strip() or "مفتاح جديد", khash, prefix, db.now_iso()),
    )
    db.audit(user["id"], "api_key_create", f"key:{kid}", {"name": body.name})
    return {
        "id": kid,
        "key": full,           # تُعرض مرة واحدة فقط
        "key_prefix": prefix,
        "name": body.name,
        "warning": "احتفظ بالمفتاح في مكان آمن — لن يُعرض مجددًا.",
    }


@router.delete("/{kid}")
def revoke_key(kid: int, user: dict = Depends(require("keys.manage"))):
    row = db.one(
        "SELECT * FROM api_keys WHERE id=? AND user_id=?", (kid, user["id"])
    )
    if not row:
        raise HTTPException(status_code=404, detail="المفتاح غير موجود")
    db.execute(
        "UPDATE api_keys SET revoked_at=? WHERE id=?", (db.now_iso(), kid)
    )
    db.audit(user["id"], "api_key_revoke", f"key:{kid}")
    return {"ok": True}

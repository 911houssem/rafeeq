# -*- coding: utf-8 -*-
"""مسارات الحسابات: إنشاء المالك، التسجيل، الدخول، والحساب الشخصي."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import billing, db, security
from .deps import get_user, is_staff, public_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SetupIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    name: str = Field(default="", max_length=100)


class LoginIn(BaseModel):
    email: str
    password: str


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    name: str = Field(default="", max_length=100)


def _issue(user: dict) -> dict:
    token = security.create_token(user["id"], user["role"])
    return {"access_token": token, "token_type": "bearer", "user": public_user(user)}


@router.get("/setup")
def setup_status():
    return {"needs_setup": not db.owner_exists()}


@router.post("/setup")
def setup(body: SetupIn):
    """إنشاء حساب المالك — يعمل مرة واحدة فقط عند أول تشغيل."""
    if db.owner_exists():
        raise HTTPException(status_code=400, detail="تم إنشاء حساب المالك مسبقًا")
    if not security.EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صالح")
    if not security.valid_password(body.password):
        raise HTTPException(status_code=400, detail="كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    uid = db.execute(
        "INSERT INTO users(email,username,display_name,password_hash,role,status,created_at) "
        "VALUES(?,?,?,?, 'owner', 'active', ?)",
        (
            body.email.lower().strip(),
            (body.name or body.email.split("@")[0]).strip(),
            (body.name or "").strip() or body.email.split("@")[0],
            security.hash_password(body.password),
            db.now_iso(),
        ),
    )
    db.audit(uid, "setup_owner", f"user:{uid}", {"email": body.email})
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    return _issue(user)


@router.post("/register")
def register(body: RegisterIn):
    if db.get_setting("allow_register", "1") != "1":
        raise HTTPException(status_code=403, detail="التسجيل مغلق حاليًا")
    if not db.owner_exists():
        raise HTTPException(status_code=400, detail="أنشئ حساب المالك أولًا")
    if not security.EMAIL_RE.match(body.email):
        raise HTTPException(status_code=400, detail="البريد الإلكتروني غير صالح")
    if not security.valid_password(body.password):
        raise HTTPException(status_code=400, detail="كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    email = body.email.lower().strip()
    if db.one("SELECT id FROM users WHERE email=?", (email,)):
        raise HTTPException(status_code=400, detail="هذا البريد مسجّل مسبقًا")
    uid = db.execute(
        "INSERT INTO users(email,username,display_name,password_hash,role,status,created_at) "
        "VALUES(?,?,?,?, 'user', 'active', ?)",
        (
            email,
            (body.name or email.split("@")[0]).strip(),
            (body.name or "").strip() or email.split("@")[0],
            security.hash_password(body.password),
            db.now_iso(),
        ),
    )
    granted = billing.grant_free_minutes(uid)
    db.audit(uid, "register", f"user:{uid}", {"free_minutes": granted})
    user = db.one("SELECT * FROM users WHERE id=?", (uid,))
    out = _issue(user)
    out["granted_minutes"] = granted
    return out


@router.post("/login")
def login(body: LoginIn):
    user = db.one("SELECT * FROM users WHERE email=?", (body.email.lower().strip(),))
    if not user or not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="البريد أو كلمة المرور غير صحيحة")
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="الحساب موقوف — تواصل مع المالك")
    db.execute("UPDATE users SET last_login_at=? WHERE id=?", (db.now_iso(), user["id"]))
    return _issue(user)


@router.get("/me")
def me(user: dict = Depends(get_user)):
    return public_user(user)


@router.post("/change-password")
def change_password(body: LoginIn, user: dict = Depends(get_user)):
    if not security.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    if not security.valid_password(body.password):
        raise HTTPException(status_code=400, detail="كلمة المرور الجديدة قصيرة")
    db.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (security.hash_password(body.password), user["id"]),
    )
    db.audit(user["id"], "change_password", f"user:{user['id']}")
    return {"ok": True}

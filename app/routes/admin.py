# -*- coding: utf-8 -*-
"""لوحة المالك/المشرف: المستخدمون، الرتب، الباقات، الإحصائيات، الإعدادات، السجل."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import billing, db, security
from ..pipeline import state as pstate
from .deps import get_user, is_owner, require

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --------------------------------------------------------------- الإحصائيات
@router.get("/stats")
def stats(user: dict = Depends(require("stats.view"))):
    out = billing.admin_stats()
    out["pipeline"] = pstate.snapshot()
    return out


@router.get("/usage")
def usage(days: int = 14, user: dict = Depends(require("stats.view"))):
    days = max(1, min(days, 90))
    daily = db.query(
        "SELECT substr(created_at,1,10) day, SUM(minutes_charged) minutes, "
        "SUM(seconds) seconds, COUNT(*) n FROM billing_log "
        "WHERE created_at >= datetime('now', ?) GROUP BY day ORDER BY day",
        (f"-{days} days",),
    )
    return {"daily": daily}


# --------------------------------------------------------------- المستخدمون
class UserPatch(BaseModel):
    role: str | None = None
    status: str | None = None
    add_minutes: int | None = None
    display_name: str | None = Field(default=None, max_length=100)
    reset_password: str | None = None
    plan_id: int | None = None


@router.get("/users")
def list_users(
    search: str = "", user: dict = Depends(require("users.manage"))
):
    q = f"%{search.strip()}%"
    rows = db.query(
        "SELECT u.id, u.email, u.display_name, u.role, u.status, u.balance_minutes, "
        "u.plan_id, u.plan_renews_at, u.plan_minutes_total, u.plan_minutes_used, "
        "u.created_at, u.last_login_at, p.name AS plan_name "
        "FROM users u LEFT JOIN plans p ON p.id=u.plan_id "
        "WHERE u.email LIKE ? OR u.display_name LIKE ? ORDER BY u.id LIMIT 300",
        (q, q),
    )
    for r in rows:
        r["role_label"] = security.ROLE_LABELS.get(r["role"], r["role"])
    return {"users": rows}


@router.patch("/users/{uid}")
def patch_user(
    uid: int, body: UserPatch, user: dict = Depends(require("users.manage"))
):
    target = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")

    # حماية: لا يمكن تعديل دور المالك إلا بواسطة المالك، ولا خفض المالك الأخير
    if target["role"] == "owner" and not is_owner(user):
        raise HTTPException(status_code=403, detail="المشرف لا يملك تعديل المالك")
    if body.role is not None:
        if body.role not in security.ROLE_LABELS:
            raise HTTPException(status_code=400, detail="رتبة غير معروفة")
        if body.role == "owner" and not is_owner(user):
            raise HTTPException(status_code=403, detail="منح رتبة المالك للمالك فقط")
        if uid == user["id"] and body.role != "owner":
            owners = db.one(
                "SELECT COUNT(*) c FROM users WHERE role='owner'"
            )["c"]
            if owners <= 1:
                raise HTTPException(
                    status_code=400, detail="لا يمكن تخفيض آخر مالك في النظام"
                )
        db.execute("UPDATE users SET role=? WHERE id=?", (body.role, uid))

    if body.status is not None:
        if body.status not in ("active", "banned"):
            raise HTTPException(status_code=400, detail="حالة غير معروفة")
        if target["role"] == "owner" and body.status != "active":
            raise HTTPException(status_code=403, detail="لا يمكن إيقاف المالك")
        db.execute("UPDATE users SET status=? WHERE id=?", (body.status, uid))

    if body.add_minutes:
        db.execute(
            "UPDATE users SET balance_minutes = balance_minutes + ? WHERE id=?",
            (int(body.add_minutes), uid),
        )

    if body.display_name is not None:
        db.execute(
            "UPDATE users SET display_name=? WHERE id=?",
            (body.display_name.strip(), uid),
        )

    if body.reset_password:
        if len(body.reset_password) < 6:
            raise HTTPException(status_code=400, detail="كلمة المرور قصيرة")
        db.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (security.hash_password(body.reset_password), uid),
        )

    if body.plan_id is not None:
        if body.plan_id == 0:
            db.execute(
                "UPDATE users SET plan_id=NULL, plan_renews_at=NULL, "
                "plan_minutes_total=0, plan_minutes_used=0 WHERE id=?",
                (uid,),
            )
        else:
            out = billing.subscribe(uid, body.plan_id)
            if not out.get("ok"):
                raise HTTPException(status_code=400, detail=out.get("error", "فشل"))

    db.audit(
        user["id"],
        "user_patch",
        f"user:{uid}",
        {k: v for k, v in body.model_dump().items() if v is not None},
    )
    fresh = db.one("SELECT * FROM users WHERE id=?", (uid,))
    from .deps import public_user

    return {"user": public_user(fresh)}


@router.delete("/users/{uid}")
def delete_user(uid: int, user: dict = Depends(require("users.manage"))):
    target = db.one("SELECT * FROM users WHERE id=?", (uid,))
    if not target:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if target["role"] == "owner":
        raise HTTPException(status_code=403, detail="لا يمكن حذف المالك")
    if uid == user["id"]:
        raise HTTPException(status_code=400, detail="لا يمكنك حذف حسابك")
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.audit(user["id"], "user_delete", f"user:{uid}", {"email": target["email"]})
    return {"ok": True}


# --------------------------------------------------------------- الباقات
class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    price: float = Field(ge=0, le=100000)
    minutes: int = Field(ge=0, le=10_000_000)
    description: str = Field(default="", max_length=300)
    is_active: bool = True
    sort: int = 0


@router.get("/plans")
def admin_plans(user: dict = Depends(require("plans.manage"))):
    rows = db.query("SELECT * FROM plans ORDER BY sort")
    subs = db.query(
        "SELECT plan_id, COUNT(*) n FROM users WHERE plan_id IS NOT NULL GROUP BY plan_id"
    )
    sub_map = {r["plan_id"]: r["n"] for r in subs}
    for r in rows:
        r["subscribers"] = sub_map.get(r["id"], 0)
    return {"plans": rows}


@router.post("/plans")
def create_plan(body: PlanIn, user: dict = Depends(require("plans.manage"))):
    pid = db.execute(
        "INSERT INTO plans(name,price,period,minutes,description,is_active,sort) "
        "VALUES(?,?, 'month', ?,?,?,?)",
        (body.name, body.price, body.minutes, body.description, int(body.is_active), body.sort),
    )
    db.audit(user["id"], "plan_create", f"plan:{pid}", body.model_dump())
    return {"id": pid}


@router.patch("/plans/{pid}")
def update_plan(pid: int, body: PlanIn, user: dict = Depends(require("plans.manage"))):
    if not db.one("SELECT id FROM plans WHERE id=?", (pid,)):
        raise HTTPException(status_code=404, detail="الباقة غير موجودة")
    db.execute(
        "UPDATE plans SET name=?, price=?, minutes=?, description=?, is_active=?, sort=? "
        "WHERE id=?",
        (body.name, body.price, body.minutes, body.description, int(body.is_active), body.sort, pid),
    )
    db.audit(user["id"], "plan_update", f"plan:{pid}", body.model_dump())
    return {"ok": True}


@router.delete("/plans/{pid}")
def delete_plan(pid: int, user: dict = Depends(require("plans.manage"))):
    used = db.one("SELECT COUNT(*) c FROM users WHERE plan_id=?", (pid,))["c"]
    if used:
        raise HTTPException(
            status_code=400, detail=f"الباقة مستخدمة لدى {used} مستخدم — عطّلها بدل حذفها"
        )
    db.execute("DELETE FROM plans WHERE id=?", (pid,))
    db.audit(user["id"], "plan_delete", f"plan:{pid}")
    return {"ok": True}


# --------------------------------------------------------------- الإعدادات
@router.get("/settings")
def get_settings_api(user: dict = Depends(require("settings.manage"))):
    return {"settings": db.get_settings()}


@router.put("/settings")
def put_settings(body: dict, user: dict = Depends(require("settings.manage"))):
    allowed = set(db.get_settings().keys())
    changed = {}
    for k, v in body.items():
        if k in allowed:
            db.set_setting(k, str(v))
            changed[k] = str(v)
    db.audit(user["id"], "settings_update", "", changed)
    return {"ok": True, "changed": changed}


# --------------------------------------------------------------- السجل
@router.get("/audit")
def audit_log(limit: int = 100, user: dict = Depends(require("audit.view"))):
    rows = db.query(
        "SELECT a.id, a.actor_id, a.action, a.target, a.meta, a.created_at, "
        "u.email AS actor_email FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id "
        "ORDER BY a.id DESC LIMIT ?",
        (max(1, min(limit, 500)),),
    )
    return {"entries": rows}


# --------------------------------------------------------------- مفاتيح الجميع
@router.get("/keys")
def all_keys(user: dict = Depends(require("keys.admin"))):
    rows = db.query(
        "SELECT k.id, k.name, k.key_prefix, k.created_at, k.last_used_at, k.revoked_at, "
        "k.user_id, u.email FROM api_keys k JOIN users u ON u.id=k.user_id "
        "ORDER BY k.id DESC LIMIT 300"
    )
    return {"keys": rows}


@router.delete("/keys/{kid}")
def admin_revoke_key(kid: int, user: dict = Depends(require("keys.admin"))):
    if not db.one("SELECT id FROM api_keys WHERE id=?", (kid,)):
        raise HTTPException(status_code=404, detail="المفتاح غير موجود")
    db.execute("UPDATE api_keys SET revoked_at=? WHERE id=?", (db.now_iso(), kid))
    db.audit(user["id"], "api_key_revoke_admin", f"key:{kid}")
    return {"ok": True}

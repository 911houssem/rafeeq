# -*- coding: utf-8 -*-
"""الفوترة بالدقيقة — الاشتراكات، الأرصدة، وخصم زمن الاستخدام (لا بالتوكن)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import db


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def renew_plan_if_due(user: dict) -> bool:
    """تجديد الاشتراك الشهري تلقائيًا إذا انتهت الفترة (تصفير العدّاد)."""
    renews = user.get("plan_renews_at")
    if not user.get("plan_id") or not renews:
        return False
    now = datetime.now(timezone.utc)
    try:
        due = _dt(renews) <= now
    except Exception:
        return False
    if due:
        # الفترة التالية تبدأ من تاريخ الاستحقاق لا من الآن
        nxt = _dt(renews)
        while nxt <= now:
            nxt = nxt + timedelta(days=30)
        db.execute(
            "UPDATE users SET plan_renews_at=?, plan_minutes_used=0 WHERE id=?",
            (nxt.isoformat(timespec="seconds"), user["id"]),
        )
        return True
    return False


def minutes_state(user_id: int) -> dict:
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        return {"plan_left": 0, "balance_left": 0, "total_left": 0}
    db.renew_plan_if_due(user)
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,)) or user
    plan_left = 0
    plan_name = None
    if user.get("plan_id") and user.get("plan_renews_at"):
        plan_left = max(0, int(user["plan_minutes_total"]) - int(user["plan_minutes_used"]))
        prow = db.one("SELECT name FROM plans WHERE id=?", (user["plan_id"],))
        plan_name = prow["name"] if prow else None
    balance = int(user["balance_minutes"])
    return {
        "plan_name": plan_name,
        "plan_left": plan_left,
        "balance_left": balance,
        "total_left": plan_left + balance,
        "renews_at": user.get("plan_renews_at"),
        "used": int(user["plan_minutes_used"]) if user.get("plan_id") else 0,
        "total": int(user["plan_minutes_total"]) if user.get("plan_id") else 0,
    }


def seconds_to_minutes(seconds: float) -> int:
    """تحويل الثواني إلى دقائق (تقريب لأعلى) مع الحد الأدنى المُهيّأ."""
    if seconds <= 0:
        return 0
    min_secs = float(db.get_setting("min_billing_seconds", "30") or 30)
    billed_secs = max(seconds, min_secs)
    return max(1, math.ceil(billed_secs / 60.0))


def charge(
    user_id: int,
    seconds: float,
    channel: str,
    detail: str = "",
    session_id: str | None = None,
) -> dict:
    """
    خصم الدقائق من رصيد المستخدم (الباقة أولًا ثم الرصيد الإضافي).
    يعيد: {charged, requested, plan_left, balance_left, ok}
    """
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        return {"charged": 0, "requested": 0, "plan_left": 0, "balance_left": 0, "ok": False}
    db.renew_plan_if_due(user)
    user = db.one("SELECT * FROM users WHERE id=?", (user_id,)) or user

    requested = seconds_to_minutes(seconds)
    plan_left = 0
    if user.get("plan_id") and user.get("plan_renews_at"):
        plan_left = max(0, int(user["plan_minutes_total"]) - int(user["plan_minutes_used"]))
    balance = int(user["balance_minutes"])

    from_plan = min(plan_left, requested)
    from_balance = min(balance, requested - from_plan)
    charged = from_plan + from_balance

    if from_plan:
        db.execute(
            "UPDATE users SET plan_minutes_used = plan_minutes_used + ? WHERE id=?",
            (from_plan, user_id),
        )
    if from_balance:
        db.execute(
            "UPDATE users SET balance_minutes = balance_minutes - ? WHERE id=?",
            (from_balance, user_id),
        )

    plan_left -= from_plan
    balance -= from_balance

    if charged or requested:
        db.execute(
            "INSERT INTO billing_log"
            "(user_id,channel,seconds,minutes_charged,plan_left,balance_left,detail,session_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                user_id,
                channel,
                round(float(seconds), 2),
                charged,
                plan_left,
                balance,
                detail,
                session_id,
                db.now_iso(),
            ),
        )
    return {
        "charged": charged,
        "requested": requested,
        "plan_left": plan_left,
        "balance_left": balance,
        "ok": charged >= requested,
    }


def has_minutes(user_id: int) -> bool:
    st = minutes_state(user_id)
    return st["total_left"] > 0


def grant_free_minutes(user_id: int) -> int:
    """منح الرصيد المجاني عند التسجيل."""
    free = int(float(db.get_setting("free_minutes_signup", "30") or 0))
    if free > 0:
        db.execute(
            "UPDATE users SET balance_minutes = balance_minutes + ? WHERE id=?",
            (free, user_id),
        )
    return free


def subscribe(user_id: int, plan_id: int) -> dict:
    """تفعيل/تجديد اشتراك شهري (في وضع الدفع التجريبي يُخصم فورًا)."""
    plan = db.one("SELECT * FROM plans WHERE id=? AND is_active=1", (plan_id,))
    if not plan:
        return {"ok": False, "error": "الباقة غير موجودة"}
    now = datetime.now(timezone.utc)
    renew = (now + timedelta(days=30)).isoformat(timespec="seconds")
    db.execute(
        "UPDATE users SET plan_id=?, plan_renews_at=?, plan_minutes_total=?, "
        "plan_minutes_used=0 WHERE id=?",
        (plan_id, renew, int(plan["minutes"]), user_id),
    )
    db.execute(
        "INSERT INTO topups(user_id,amount,minutes,method,status,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, float(plan["price"]), int(plan["minutes"]), "plan", "completed", db.now_iso()),
    )
    db.audit(user_id, "subscribe", f"plan:{plan_id}", {"plan": plan["name"]})
    return {"ok": True, "state": minutes_state(user_id)}


def topup(user_id: int, amount: float, minutes: int, method: str = "demo") -> dict:
    """شحن رصيد دقائق (ربط بوابة دفع حقيقية لاحقًا — حاليًا وضع تجريبي)."""
    if minutes <= 0:
        return {"ok": False, "error": "قيمة غير صالحة"}
    db.execute(
        "UPDATE users SET balance_minutes = balance_minutes + ? WHERE id=?",
        (minutes, user_id),
    )
    db.execute(
        "INSERT INTO topups(user_id,amount,minutes,method,status,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, float(amount), int(minutes), method, "completed", db.now_iso()),
    )
    db.audit(user_id, "topup", f"minutes:{minutes}", {"amount": amount, "method": method})
    return {"ok": True, "state": minutes_state(user_id)}


def usage_history(user_id: int, limit: int = 30) -> list[dict]:
    return db.query(
        "SELECT channel, seconds, minutes_charged, plan_left, balance_left, detail, created_at "
        "FROM billing_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )


def admin_stats() -> dict:
    from . import config as _c

    now = datetime.now(timezone.utc)
    today = now.isoformat(timespec="seconds")[:10]
    users_total = db.one("SELECT COUNT(*) c FROM users")["c"]
    users_active = db.one("SELECT COUNT(*) c FROM users WHERE status='active'")["c"]
    owners = db.one("SELECT COUNT(*) c FROM users WHERE role='owner'")["c"]
    admins = db.one("SELECT COUNT(*) c FROM users WHERE role='admin'")["c"]
    subs = db.one(
        "SELECT COUNT(*) c FROM users WHERE plan_id IS NOT NULL AND plan_renews_at > ?",
        (now.isoformat(timespec="seconds"),),
    )["c"]
    m_today = db.one(
        "SELECT COALESCE(SUM(minutes_charged),0) m FROM billing_log WHERE created_at LIKE ?",
        (today + "%",),
    )["m"]
    m_30 = db.one(
        "SELECT COALESCE(SUM(minutes_charged),0) m FROM billing_log "
        "WHERE created_at >= datetime('now','-30 days')"
    )["m"]
    price = float(db.get_setting("price_per_minute", "0.5") or 0.5)
    revenue_est = round(m_30 * price, 2)
    # استهلاك آخر 14 يومًا للرسم البياني
    daily = db.query(
        "SELECT substr(created_at,1,10) day, SUM(minutes_charged) m, COUNT(*) n "
        "FROM billing_log WHERE created_at >= datetime('now','-14 days') "
        "GROUP BY day ORDER BY day"
    )
    channels = db.query(
        "SELECT channel, SUM(minutes_charged) m, COUNT(*) n FROM billing_log "
        "GROUP BY channel ORDER BY m DESC"
    )
    keys_count = db.one(
        "SELECT COUNT(*) c FROM api_keys WHERE revoked_at IS NULL"
    )["c"]
    return {
        "users_total": users_total,
        "users_active": users_active,
        "owners": owners,
        "admins": admins,
        "active_subscriptions": subs,
        "minutes_today": m_today,
        "minutes_30d": m_30,
        "revenue_est_30d": revenue_est,
        "currency": db.get_setting("currency", _c.DEFAULT_SETTINGS["currency"]),
        "price_per_minute": price,
        "daily": daily,
        "channels": channels,
        "api_keys_active": keys_count,
    }

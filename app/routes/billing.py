# -*- coding: utf-8 -*-
"""الفوترة: الباقات، الاشتراك، الشحن، السجل — كلها بالدقيقة (لا بالتوكن)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import billing, db
from .. import config as cfg
from .deps import get_user, require

router = APIRouter(prefix="/api/billing", tags=["billing"])


class SubscribeIn(BaseModel):
    plan_id: int


class TopupIn(BaseModel):
    pack: int = Field(ge=0, le=2)  # فهرس حزمة الشحن


@router.get("/plans")
def plans():
    rows = db.query(
        "SELECT id, name, price, period, minutes, description, sort FROM plans "
        "WHERE is_active=1 ORDER BY sort"
    )
    packs = [
        {"index": i, "amount": a, "minutes": m}
        for i, (a, m) in enumerate(cfg.DEFAULT_TOPUPS)
    ]
    settings = db.get_settings(["price_per_minute", "currency", "free_minutes_signup"])
    return {
        "plans": rows,
        "topup_packs": packs,
        "price_per_minute": float(settings["price_per_minute"]),
        "currency": settings["currency"],
        "free_minutes_signup": settings["free_minutes_signup"],
        "billing_note": (
            "الفوترة بالدقيقة: كل تفاعل يُحتسب بأقل من دقيقة يُحتسب دقيقة كاملة، "
            "والجلسات الصوتية تُحتسب بمدة الاستخدام الفعلية سجلاً سجلاً."
        ),
    }


@router.get("/me")
def mine(user: dict = Depends(require("billing.view"))):
    state = billing.minutes_state(user["id"])
    history = billing.usage_history(user["id"], 40)
    return {
        "state": state,
        "history": history,
        "price_per_minute": float(db.get_setting("price_per_minute", "0.5")),
        "currency": db.get_setting("currency", "ر.س"),
        "free": user["role"] in ("owner", "admin"),
    }


@router.post("/subscribe")
def subscribe(body: SubscribeIn, user: dict = Depends(require("billing.topup"))):
    out = billing.subscribe(user["id"], body.plan_id)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("error", "فشل الاشتراك"))
    return out


@router.post("/topup")
def topup(body: TopupIn, user: dict = Depends(require("billing.topup"))):
    from .. import config as cfg

    if body.pack < 0 or body.pack >= len(cfg.DEFAULT_TOPUPS):
        raise HTTPException(status_code=400, detail="حزمة غير صالحة")
    amount, minutes = cfg.DEFAULT_TOPUPS[body.pack]
    out = billing.topup(user["id"], amount, minutes, method="demo")
    return out

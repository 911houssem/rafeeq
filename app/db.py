# -*- coding: utf-8 -*-
"""طبقة قاعدة البيانات (SQLite) — مخطط الجداول والدوال المساعدة."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

_local = threading.local()
_write_lock = threading.RLock()
_initialized = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(str(config.DB_PATH), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    cur = get_conn().execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def one(sql: str, params: tuple | list = ()) -> Optional[dict]:
    cur = get_conn().execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def execute(sql: str, params: tuple | list = ()) -> int:
    with _write_lock:
        conn = get_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0


def executescript(sql: str) -> None:
    with _write_lock:
        conn = get_conn()
        conn.executescript(sql)
        conn.commit()


def get_setting(key: str, default: str | None = None) -> str:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    if row:
        return row["value"]
    if default is not None:
        return default
    return config.DEFAULT_SETTINGS.get(key, "")


def get_settings(keys: list[str] | None = None) -> dict[str, str]:
    keys = keys or list(config.DEFAULT_SETTINGS.keys())
    rows = query(
        "SELECT key, value FROM settings WHERE key IN (%s)" % ",".join("?" * len(keys)),
        keys,
    )
    out = {r["key"]: r["value"] for r in rows}
    for k in keys:
        out.setdefault(k, config.DEFAULT_SETTINGS.get(k, ""))
    return out


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def audit(actor_id: int | None, action: str, target: str = "", meta: dict | None = None) -> None:
    execute(
        "INSERT INTO audit_log(actor_id,action,target,meta,created_at) VALUES(?,?,?,?,?)",
        (actor_id, action, target, json.dumps(meta or {}, ensure_ascii=False), now_iso()),
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    period TEXT NOT NULL DEFAULT 'month',
    minutes INTEGER NOT NULL DEFAULT 0,
    description TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',            -- owner | admin | user
    status TEXT NOT NULL DEFAULT 'active',        -- active | banned
    balance_minutes INTEGER NOT NULL DEFAULT 0,   -- رصيد الدقائق الإضافي
    plan_id INTEGER REFERENCES plans(id),
    plan_renews_at TEXT,
    plan_minutes_total INTEGER NOT NULL DEFAULT 0,
    plan_minutes_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS billing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,                        -- voice | chat | api_chat | transcribe | speech
    seconds REAL NOT NULL DEFAULT 0,
    minutes_charged INTEGER NOT NULL DEFAULT 0,
    plan_left INTEGER NOT NULL DEFAULT 0,
    balance_left INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS topups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount REAL NOT NULL,
    minutes INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT 'demo',
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT 'محادثة جديدة',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,                           -- user | assistant
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_billing_user ON billing_log(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_keys_user ON api_keys(user_id);
"""


def init_db() -> None:
    """إنشاء الجداول + الإعدادات والباقات الافتراضية (مرة واحدة)."""
    global _initialized
    if _initialized:
        return
    executescript(SCHEMA)
    # الإعدادات الافتراضية
    for k, v in config.DEFAULT_SETTINGS.items():
        execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
        )
    # الباقات الافتراضية
    if not one("SELECT id FROM plans LIMIT 1"):
        for name, price, minutes, desc, sort in config.DEFAULT_PLANS:
            execute(
                "INSERT INTO plans(name,price,period,minutes,description,is_active,sort) "
                "VALUES(?,?, 'month', ?, ?, 1, ?)",
                (name, price, minutes, desc, sort),
            )
    _initialized = True


def owner_exists() -> bool:
    return one("SELECT id FROM users WHERE role='owner' LIMIT 1") is not None


def user_minutes_state(user: dict) -> dict:
    """حالة رصيد الدقائق للمستخدم (مع تجديد الاشتراك إن انتهت الفترة)."""
    from . import billing  # تفادي ت circular

    billing.renew_plan_if_due(user)
    user = one("SELECT * FROM users WHERE id=?", (user["id"],)) or user
    plan_left = 0
    plan_name = None
    if user.get("plan_id") and user.get("plan_renews_at"):
        plan_left = max(0, int(user["plan_minutes_total"]) - int(user["plan_minutes_used"]))
        prow = one("SELECT name FROM plans WHERE id=?", (user["plan_id"],))
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

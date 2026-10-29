# -*- coding: utf-8 -*-
"""أدوات البث: تحويل مُولِّد تزامني إلى غير تزامني عبر طابور (للاستخدام في FastAPI)."""
from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncIterator, Iterable, Optional


def aiter_threaded(
    sync_gen: Iterable[Any],
    stop_event: Optional[threading.Event] = None,
    maxsize: int = 64,
) -> AsyncIterator[Any]:
    """
    يُغلف مُولِّد تزامني (يمنع الحلقة) ويُعيده كمُولِّد غير تزامني.
    عند إلغاء الـ async generator يُوقف التوليد في الخلفية.
    """
    q: queue.Queue = queue.Queue(maxsize=maxsize)
    _DONE = object()
    _ERR = object()

    def worker():
        try:
            for item in sync_gen:
                q.put(("data", item))
        except Exception as e:  # noqa: BLE001
            q.put((_ERR, e))
        finally:
            q.put((_DONE, None))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    async def gen():
        loop = asyncio.get_running_loop()
        try:
            while True:
                kind, item = await loop.run_in_executor(None, q.get)
                if kind is _DONE:
                    break
                if kind is _ERR:
                    raise item
                yield item
        finally:
            if stop_event is not None:
                stop_event.set()
            # تفريغ الطابور حتى لا يعلّق عامل الخلفية
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass

    return gen()


async def run_sync(fn, *args, **kwargs):
    """تشغيل دالة تزامنية (النماذج) في خيط منفصل."""
    return await asyncio.get_running_loop().run_in_executor(
        None, lambda: fn(*args, **kwargs)
    )

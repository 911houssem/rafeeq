# -*- coding: utf-8 -*-
"""
محرك التفكير — Jais-3-7B من ملفاتك الأصلية (مجلد «التفكير Jais 3 7B»).
بثّ مباشر (streaming) مع فصل «التفكير» عن «الجواب» بشفافية.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Iterator, Optional

from .. import config
from . import state

# علامات قالب jais/k2_horizon
_THINK_OPEN = "<ifm|think"
_THINK_CLOSE = "</ifm|think"
_TURN_END = "<|ifm|im_end|>"


class StreamParser:
    """
    يفصل تدفق الرد إلى: تفكير (لا يُعرض صوتيًا) ← جواب (يُبث للمستخدم).
    يبدأ بمرحلة «التفكير» لأن القالب يفتح وسم التفكير في نهاية الـ prompt.
    """

    def __init__(self, max_think_chars: int = 6000):
        self.phase = "think"          # think | content | done
        self.raw = ""
        self.consumed = 0
        self.max_think_chars = max_think_chars

    def feed(self, piece: str) -> list[tuple[str, str]]:
        """يعيد قائمة (نوع, نص) — النوع: think | content | done"""
        if not piece or self.phase == "done":
            return []
        self.raw += piece
        events: list[tuple[str, str]] = []
        while True:
            if self.phase == "think":
                idx = self.raw.find(_THINK_CLOSE, self.consumed)
                # احتفظ بجزء من النص لالتقاط الوسم مقسّمًا بين القطع
                hold = len(_THINK_CLOSE) + 12
                limit = len(self.raw) - hold
                if idx == -1 or idx > limit:
                    # أرسل جزء التفكير (اختياريًا) مع احتباس الذيل
                    end = max(self.consumed, min(limit, self.consumed + 4000))
                    if end > self.consumed and limit >= self.consumed:
                        chunk = self.raw[self.consumed : end]
                        if chunk:
                            events.append(("think", chunk))
                            self.consumed = end
                    if idx != -1 and idx <= limit:
                        self.raw = self.raw[idx:]
                        self.consumed = 0
                        self.phase = "content"
                        continue
                    if len(self.raw) - self.consumed > self.max_think_chars:
                        # تفكير طويل جدًا: اعتبر الباقي جوابًا
                        self.phase = "content"
                        continue
                    break
                # وُجد إغلاق التفكير ضمن الحدود
                think_chunk = self.raw[self.consumed : idx]
                if think_chunk:
                    events.append(("think", think_chunk))
                self.raw = self.raw[idx + len(_THINK_CLOSE) :]
                # ابتلع وسم الإغلاق الكامل: </ifm|think...>
                gt = self.raw.find(">")
                if gt == -1:
                    break
                self.raw = self.raw[gt + 1 :]
                self.consumed = 0
                self.phase = "content"
                continue

            if self.phase == "content":
                idx = self.raw.find(_TURN_END, self.consumed)
                hold = len(_TURN_END)
                limit = len(self.raw) - hold
                if idx == -1 or idx > limit:
                    end = max(self.consumed, limit) if limit > self.consumed else self.consumed
                    if end > self.consumed:
                        events.append(("content", self.raw[self.consumed : end]))
                        self.consumed = end
                    if idx != -1 and idx <= limit:
                        events.append(("done", ""))
                        self.phase = "done"
                    break
                chunk = self.raw[self.consumed : idx]
                if chunk:
                    events.append(("content", chunk))
                events.append(("done", ""))
                self.phase = "done"
                break
        return events

    def flush(self) -> list[tuple[str, str]]:
        if self.phase == "done":
            return []
        rest = self.raw[self.consumed :]
        self.consumed = len(self.raw)
        out: list[tuple[str, str]] = []
        if rest and self.phase == "think":
            out.append(("think", rest))
        elif rest:
            out.append(("content", rest))
        self.phase = "done"
        return out


class _StopOnEvent:
    """معيار إيقاف التوليد عند طلب المقاطعة (barge-in)."""

    def __init__(self, event: threading.Event):
        self.event = event

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        return self.event.is_set()


class JaisLLM:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._lock = threading.Lock()

    # ------------------------------------------------ التحميل
    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            t0 = time.time()
            state.mark_loading("llm")
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoTokenizer

                path = str(config.MODEL_LLM_DIR)
                if not config.MODEL_LLM_DIR.exists():
                    raise FileNotFoundError(f"مجلد النموذج غير موجود: {path}")

                dtype = getattr(torch, config.LLM_DTYPE, torch.bfloat16)
                self.tokenizer = AutoTokenizer.from_pretrained(
                    path, trust_remote_code=True, local_files_only=True
                )
                try:
                    self.model = AutoModelForCausalLM.from_pretrained(
                        path,
                        trust_remote_code=True,
                        local_files_only=True,
                        device_map="auto",
                        dtype=dtype,
                        low_cpu_mem_usage=True,
                    ).eval()
                except (torch.cuda.OutOfMemoryError, OSError, MemoryError) as e:
                    if not config.AUTO_OFFLOAD_ON_OOM:
                        raise
                    # نقص الذاكرة: ترحيل جزء من الطبقات إلى القرص
                    self.model = AutoModelForCausalLM.from_pretrained(
                        path,
                        trust_remote_code=True,
                        local_files_only=True,
                        device_map="auto",
                        max_memory={"cpu": "5GB", "disk": "45GB"},
                        offload_folder=str(config.OFFLOAD_DIR),
                        offload_state_dict=True,
                        dtype=dtype,
                        low_cpu_mem_usage=True,
                    ).eval()
                    self.model._rafeeq_offloaded = True  # type: ignore[attr-defined]
                state.mark_ready("llm", time.time() - t0)
            except Exception as e:
                state.mark_error("llm", f"{type(e).__name__}: {e}")
                raise

    def unload(self) -> None:
        with self._lock:
            self.model = None
            self.tokenizer = None
            try:
                import gc

                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            state.STATE["llm"].set("idle")

    # ------------------------------------------------ التوليد المتدفق
    def stream(
        self,
        messages: list[dict],
        *,
        max_new_tokens: int = 260,
        temperature: float = 0.7,
        top_p: float = 0.95,
        top_k: int = 20,
        reasoning_effort: str = "low",
        stop_event: Optional[threading.Event] = None,
        on_state: Optional[Callable[[str], None]] = None,
    ) -> Iterator[tuple[str, str]]:
        """
        يُولّد الرد تدريجيًا.
        يُعيد أزواج (نوع, نص): ("think", ...) للتفكير — ("content", ...) للجواب — ("done", "").
        """
        if self.model is None:
            self.load()
        import torch
        from transformers import StoppingCriteriaList, TextIteratorStreamer

        # القالب يتطلب حقل تفكير في رسائل المساعد السابقة
        tpl_msgs: list[dict] = []
        for m in messages:
            mm = dict(m)
            if mm.get("role") == "assistant" and not any(
                k in mm
                for k in ("think", "think_fast", "think_faster", "reasoning", "reasoning_content")
            ):
                mm["think"] = ""
            tpl_msgs.append(mm)

        effort = reasoning_effort if reasoning_effort in ("high", "medium", "low") else "low"
        try:
            prompt = self.tokenizer.apply_chat_template(
                tpl_msgs,
                tokenize=False,
                add_generation_prompt=True,
                chat_template_kwargs={"reasoning_effort": effort},
            )
        except TypeError:
            prompt = self.tokenizer.apply_chat_template(
                tpl_msgs, tokenize=False, add_generation_prompt=True, reasoning_effort=effort
            )

        inputs = self.tokenizer(prompt, return_tensors="pt")
        inputs.pop("token_type_ids", None)
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}

        streamer = TextIteratorStreamer(
            self.tokenizer, skip_prompt=True, skip_special_tokens=True, timeout=120
        )
        ev = stop_event or threading.Event()

        gen_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=int(max_new_tokens),
            use_cache=True,
            stopping_criteria=StoppingCriteriaList([_StopOnEvent(ev)]),
        )
        if temperature and float(temperature) > 0:
            gen_kwargs.update(
                do_sample=True,
                temperature=float(temperature),
                top_p=float(top_p),
                top_k=int(top_k),
            )
        else:
            gen_kwargs["do_sample"] = False

        def _run():
            try:
                with torch.inference_mode():
                    self.model.generate(**gen_kwargs)
            except Exception:
                # إغلاق الطابور حتى لا يعلّق القارئ
                try:
                    streamer.end()
                except Exception:
                    pass

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        parser = StreamParser()
        try:
            for piece in streamer:
                if ev.is_set():
                    break
                for kind, text in parser.feed(piece):
                    if kind == "content" and on_state:
                        on_state("content")
                    elif kind == "think" and on_state:
                        on_state("think")
                    yield kind, text
                if parser.phase == "done":
                    break
            if not ev.is_set():
                for kind, text in parser.flush():
                    yield kind, text
                    if kind == "content" and on_state:
                        on_state("content")
        finally:
            ev.set()  # ضمان إيقاف التوليد عند الخروج المبكر
            thread.join(timeout=5)

    def generate_once(self, messages: list[dict], **kw) -> str:
        """توليد كامل غير متدفق (للاستخدام الداخلي/الاختبارات)."""
        parts: list[str] = []
        for kind, text in self.stream(messages, **kw):
            if kind == "content":
                parts.append(text)
        return "".join(parts)


llm = JaisLLM()


def get_llm() -> JaisLLM:
    if llm.model is None:
        llm.load()
    return llm

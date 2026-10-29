# -*- coding: utf-8 -*-
"""
محرك الاستماع — Jais-ASR من ملفاتك الأصلية (مجلد «الاستماع Jais-ASR»).
تحويل الصوت إلى نص بالعربية واللهجات + كشف اللغة واللهجة.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .. import config
from . import state
from .audio import pcm16_to_float


class JaisASR:
    def __init__(self):
        self.model = None
        self.processor = None
        self._lock = threading.Lock()

    # ------------------------------------------------ التحميل
    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            t0 = time.time()
            state.mark_loading("asr")
            try:
                import torch
                from transformers import AutoModelForCausalLM, AutoProcessor

                path = str(config.MODEL_ASR_DIR)
                if not config.MODEL_ASR_DIR.exists():
                    raise FileNotFoundError(f"مجلد النموذج غير موجود: {path}")

                dtype = getattr(torch, config.ASR_DTYPE, torch.bfloat16)
                self.processor = AutoProcessor.from_pretrained(
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
                    # نقص الذاكرة: ترحيل جزء من الأوزان إلى القرص
                    self.model = AutoModelForCausalLM.from_pretrained(
                        path,
                        trust_remote_code=True,
                        local_files_only=True,
                        device_map="auto",
                        max_memory={"cpu": "5GB", "disk": "40GB"},
                        offload_folder=str(config.OFFLOAD_DIR),
                        offload_state_dict=True,
                        dtype=dtype,
                        low_cpu_mem_usage=True,
                    ).eval()
                    self.model._rafeeq_offloaded = True  # type: ignore[attr-defined]
                state.mark_ready("asr", time.time() - t0)
            except Exception as e:
                state.mark_error("asr", f"{type(e).__name__}: {e}")
                raise

    def unload(self) -> None:
        with self._lock:
            self.model = None
            self.processor = None
            try:
                import gc

                import torch

                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            state.STATE["asr"].set("idle")

    # ------------------------------------------------ التفريغ
    def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        language: Optional[str] = None,
        diacritics: bool = False,
        code_switch: bool = True,
        max_new_tokens: int = 384,
    ) -> dict:
        """
        pcm: بايتات PCM16 أحادية.
        يعيد: {"text", "language", "refused"}
        """
        if not pcm:
            return {"text": "", "language": None, "refused": True}
        if self.model is None:
            self.load()
        with self._lock:
            import torch

            waveform = pcm16_to_float(pcm).astype(np.float32)
            prompt = self.processor.tokenizer.apply_chat_template(
                [{"role": "user", "content": [{"type": "audio"}]}],
                tokenize=False,
                add_generation_prompt=True,
                diacritics=diacritics,
                code_switch=code_switch,
            )
            inputs = self.processor(
                text=[prompt],
                audio=[waveform],
                sampling_rate=[sample_rate],
                return_tensors="pt",
            )
            gen_kwargs = dict(
                do_sample=False,
                max_new_tokens=max_new_tokens,
            )
            if language:
                gen_kwargs["language"] = language
            with torch.inference_mode():
                output = self.model.generate(**inputs, **gen_kwargs)
            results = self.processor.post_process_transcription(
                output, input_lengths=inputs["input_ids"].shape[1]
            )
            res = results[0]
            text = (getattr(res, "text", "") or "").strip()
            refused = bool(getattr(res, "refused", False)) or text == "[IFM-NoTranscript]"
            return {
                "text": "" if refused else text,
                "language": getattr(res, "language", None),
                "refused": refused,
            }


# نسخة واحدة عامة
asr = JaisASR()


def get_asr() -> JaisASR:
    if asr.model is None:
        asr.load()
    return asr

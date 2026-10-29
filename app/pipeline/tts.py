# -*- coding: utf-8 -*-
"""
محرك الكلام — SILMA TTS من ملفاتك الأصلية
(مجلد «التحدث SILMA TTS»: model.pt + config.yaml + vocab.txt).
تحويل النص إلى صوت عربي طبيعي بزمن استجابة منخفض (جُملة تلو الأخرى).
"""
from __future__ import annotations

import sys
import threading
import time
import warnings
from pathlib import Path

# تهيئة مسار الوحدات المحلية قبل استيراد silma_tts
_VENDOR = Path(__file__).resolve().parents[2] / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

import matplotlib

matplotlib.use("Agg")

import numpy as np

from .. import config
from . import state
from .audio import float_to_pcm16

# النص المرجعي للصوت الافتراضي (مصاحب لعينة الصوت داخل حزمة SILMA)
DEFAULT_REF_TEXT = (
    "ويدقق النظر في القرآن الكريم وسائر الكتب السماوية ويتبع مسالك الرسل العظام "
    "عليهم الصلاة والسلام."
)
_BUNDLED_REF = Path(__file__).resolve().parents[3].parent  # placeholder


def _find_ref_audio() -> Path:
    """عينة الصوت المرجعي: data/voice/ref.wav إن وجدت، وإلا العينة المضمّنة بالحزمة."""
    custom = config.VOICE_DIR / "ref.wav"
    if custom.exists():
        return custom
    try:
        from importlib.resources import files

        p = Path(str(files("silma_tts").joinpath("infer/ref_audio_samples/ar.ref.24k.wav")))
        if p.exists():
            return p
    except Exception:
        pass
    raise FileNotFoundError("لم يتم العثور على عينة الصوت المرجعي")


class _QuietProgress:
    """كائن بديل عن tqdm لمنع طباعة أشرطة التقدم في الخادم."""

    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return self

    def update(self, *a, **k):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_TORCHAUDIO_PATCHED = False


def _patch_torchaudio() -> None:
    """
    torchaudio.load يتطلب torchcodec + FFmpeg (غير مثبّتين على الجهاز).
    نُعِّض التحميل بـ soundfile مباشرة — ملفاتنا كلها WAV.
    """
    global _TORCHAUDIO_PATCHED
    if _TORCHAUDIO_PATCHED:
        return
    try:
        import soundfile as sf
        import torch
        import torchaudio

        def _load(path, *a, **k):
            data, sr = sf.read(str(path), dtype="float32", always_2d=True)
            tensor = torch.from_numpy(np.ascontiguousarray(data.T))
            return tensor, int(sr)

        def _save(path, tensor, sr, *a, **k):
            arr = tensor.detach().cpu().numpy()
            if arr.ndim > 1:
                arr = arr.T  # (time, channels)
            sf.write(str(path), arr, int(sr))

        torchaudio.load = _load
        torchaudio.save = _save
        _TORCHAUDIO_PATCHED = True
    except Exception as e:  # noqa: BLE001
        warnings.warn(f"تعذر ترقيع torchaudio: {e}")


class SilmaEngine:
    def __init__(self):
        self.model = None
        self.vocoder = None
        self.mel_spec_type = "vocos"
        self.target_sample_rate = config.TTS_RATE
        self.device = "cpu"
        self.ref_file: str = ""
        self.ref_text: str = DEFAULT_REF_TEXT
        self._lock = threading.Lock()
        self._nfe = 16
        self._cfg_strength = 2.0

    # -------------------------------------------------- التحميل
    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            t0 = time.time()
            state.mark_loading("tts")
            try:
                import torch
                from hydra.utils import get_class
                from omegaconf import OmegaConf

                _patch_torchaudio()

                tdir = config.MODEL_TTS_DIR
                if not tdir.exists():
                    raise FileNotFoundError(f"مجلد النموذج غير موجود: {tdir}")

                cfg = OmegaConf.load(str(tdir / "config.yaml"))
                self.mel_spec_type = cfg.model.mel_spec.mel_spec_type
                self.target_sample_rate = int(cfg.model.mel_spec.target_sample_rate)

                device = "cuda" if torch.cuda.is_available() else "cpu"
                self.device = device

                from silma_tts.infer.utils_infer import load_model, load_vocoder

                model_cls = get_class(f"silma_tts.model.{cfg.model.backbone}")
                self.model = load_model(
                    model_cls,
                    cfg.model.arch,
                    str(tdir / "model.pt"),       # أوزانك الأصلية
                    self.mel_spec_type,
                    str(tdir / "vocab.txt"),      # قاموسك الأصلي
                    "euler",
                    False,
                    device,
                )
                self.vocoder = load_vocoder(
                    self.mel_spec_type, False, "", device, None
                )

                # الصوت المرجعي (voice cloning)
                self.ref_file = str(_find_ref_audio())
                custom_txt = (config.VOICE_DIR / "ref.txt")
                if custom_txt.exists():
                    self.ref_text = custom_txt.read_text(encoding="utf-8").strip() or DEFAULT_REF_TEXT

                # تهيئة مُطبِّع الأرقام والتشكيل مرة واحدة
                from silma_tts.infer.utils_infer import (
                    load_nemo_text_normalizer,
                    load_tashkeel_model,
                )

                load_nemo_text_normalizer("english")
                load_nemo_text_normalizer("عربي")
                try:
                    load_tashkeel_model()
                except Exception as e:  # التشكيل تحسين اختياري
                    warnings.warn(f"تعذر تحميل نموذج التشكيل: {e}")

                # معالجة الصوت المرجعي مسبقًا (تُخزَّن مؤقتًا داخل الحزمة)
                from silma_tts.infer.utils_infer import preprocess_ref_audio_text

                self.ref_file, self.ref_text = preprocess_ref_audio_text(
                    self.ref_file, self.ref_text, show_info=lambda *a, **k: None
                )

                state.mark_ready("tts", time.time() - t0)
            except Exception as e:
                state.mark_error("tts", f"{type(e).__name__}: {e}")
                raise

    def unload(self) -> None:
        with self._lock:
            self.model = None
            self.vocoder = None
            try:
                import gc

                gc.collect()
            except Exception:
                pass
            state.STATE["tts"].set("idle")

    # -------------------------------------------------- التوليد
    def synthesize(
        self,
        text: str,
        speed: float | None = None,
        nfe_step: int | None = None,
        cfg_strength: float | None = None,
        force_tashkeel: bool = True,
        seed: int | None = None,
    ) -> tuple[bytes, int]:
        """
        نص → PCM16 (مع معدل العينة الأصلي للنموذج).
        يعيد: (بايتات pcm16, sample_rate)
        """
        text = (text or "").strip()
        if not text:
            return b"", self.target_sample_rate
        if self.model is None:
            self.load()
        with self._lock:
            from silma_tts.infer.utils_infer import infer_process

            if speed is None:
                speed = float(db_safe_speed())
            if nfe_step is None:
                nfe_step = self._nfe
            if cfg_strength is None:
                cfg_strength = self._cfg_strength

            wav, sr, _spec = infer_process(
                self.ref_file,
                self.ref_text,
                text,
                self.model,
                self.vocoder,
                self.mel_spec_type,
                show_info=lambda *a, **k: None,
                progress=None,
                target_rms=0.1,
                cross_fade_duration=0,
                nfe_step=int(nfe_step),
                cfg_strength=float(cfg_strength),
                sway_sampling_coef=-1,
                speed=float(speed),
                fix_duration=None,
                device=self.device,
                force_tashkeel=bool(force_tashkeel),
            )
            if isinstance(wav, np.ndarray):
                if wav.dtype != np.float32:
                    wav = wav.astype(np.float32)
                pcm = float_to_pcm16(np.asarray(wav, dtype=np.float32).reshape(-1))
            else:  # بيانات خام غير متوقعة
                pcm = np.asarray(wav, dtype=np.float32).reshape(-1)
                pcm = float_to_pcm16(pcm)
            return pcm, int(sr or self.target_sample_rate)


def db_safe_speed() -> float:
    try:
        from .. import db

        return float(db.get_setting("tts_speed", "1.0") or 1.0)
    except Exception:
        return 1.0


engine = SilmaEngine()


def get_tts() -> SilmaEngine:
    if engine.model is None:
        engine.load()
    return engine

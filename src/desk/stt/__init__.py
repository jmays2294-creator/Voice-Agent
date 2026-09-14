"""Speech-in backends. On-device only — speech never leaves the Mac.

CTranslate2, which `faster-whisper` runs on, has no Metal backend: on a Mac it
silently transcribes on the CPU. `mlx-whisper` runs the same model on the GPU
for roughly a 7x speedup on M-series with an identical transcript, which is the
difference between meeting the 200ms budget and missing it. So the selection is
by hardware, not by preference.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio, sample_rate: int) -> str: ...

    def prewarm(self) -> None: ...


class TranscriberUnavailable(RuntimeError):
    pass


#: Marks a model that lives in Desk's own verified models directory, rather
#: than being pulled from a hub cache at load time. Rule 5 only means anything
#: when the file that was hashed is the file that gets opened, so this is the
#: form the daemon expects and `verify_boot` complains about anything else.
LOCAL_PREFIX = "local:"


def resolve_model(model: str) -> str:
    """Turn `local:<name>` into an absolute path under the models directory.

    Anything else is passed through untouched — a hub repo id still works, it
    just cannot be covered by the weight pins.
    """
    if not model.startswith(LOCAL_PREFIX):
        return model
    from .. import paths

    name = model[len(LOCAL_PREFIX):].strip("/")
    if not name or ".." in Path(name).parts:
        raise TranscriberUnavailable(f"{model!r} is not a usable local model name")
    return str(paths.models_dir() / name)


def is_local(model: str) -> bool:
    return model.startswith(LOCAL_PREFIX)


def create(backend: str = "auto", model: str = "mlx-community/whisper-small.en-mlx"):
    from ..config import is_apple_silicon

    chosen = backend
    if backend == "auto":
        chosen = "mlx" if is_apple_silicon() else "faster-whisper"

    if chosen == "mlx":
        from .mlx_backend import MLXTranscriber
        return MLXTranscriber(resolve_model(model))
    if chosen == "faster-whisper":
        from .fw_backend import FasterWhisperTranscriber
        return FasterWhisperTranscriber(model)
    raise TranscriberUnavailable(f"unknown speech-in backend {backend!r}")

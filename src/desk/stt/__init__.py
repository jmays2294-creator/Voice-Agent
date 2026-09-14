"""Speech-in backends. On-device only — speech never leaves the Mac.

CTranslate2, which `faster-whisper` runs on, has no Metal backend: on a Mac it
silently transcribes on the CPU. `mlx-whisper` runs the same model on the GPU
for roughly a 7x speedup on M-series with an identical transcript, which is the
difference between meeting the 200ms budget and missing it. So the selection is
by hardware, not by preference.
"""

from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio, sample_rate: int) -> str: ...

    def prewarm(self) -> None: ...


class TranscriberUnavailable(RuntimeError):
    pass


def create(backend: str = "auto", model: str = "mlx-community/whisper-small.en-mlx"):
    from ..config import is_apple_silicon

    chosen = backend
    if backend == "auto":
        chosen = "mlx" if is_apple_silicon() else "faster-whisper"

    if chosen == "mlx":
        from .mlx_backend import MLXTranscriber
        return MLXTranscriber(model)
    if chosen == "faster-whisper":
        from .fw_backend import FasterWhisperTranscriber
        return FasterWhisperTranscriber(model)
    raise TranscriberUnavailable(f"unknown speech-in backend {backend!r}")

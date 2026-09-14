"""faster-whisper fallback.

CPU-bound on a Mac — CTranslate2 has no Metal backend — so this is the fallback
and never the default on Apple Silicon.
"""

from __future__ import annotations

from . import TranscriberUnavailable


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(self, model: str) -> None:
        # Accept an MLX repo id and map it to the plain model size.
        self.model = model.split("/")[-1].replace("whisper-", "").replace("-mlx", "")
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel  # type: ignore
            except ImportError as exc:  # pragma: no cover - platform specific
                raise TranscriberUnavailable(
                    "faster-whisper is not installed. Install the [fallback] extra."
                ) from exc
            self._model = WhisperModel(self.model, device="cpu", compute_type="int8")
        return self._model

    def prewarm(self) -> None:
        import numpy as np

        model = self._load()
        list(model.transcribe(np.zeros(16000, dtype="float32"), language="en")[0])

    def transcribe(self, audio, sample_rate: int) -> str:
        model = self._load()
        segments, _ = model.transcribe(audio, language="en", vad_filter=False,
                                       condition_on_previous_text=False)
        return "".join(s.text for s in segments)

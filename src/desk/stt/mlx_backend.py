"""mlx-whisper on the Apple Silicon GPU. The default on this hardware."""

from __future__ import annotations

from . import TranscriberUnavailable


class MLXTranscriber:
    name = "mlx-whisper"

    def __init__(self, model: str) -> None:
        self.model = model
        self._mod = None

    def _load(self):
        if self._mod is None:
            try:
                import mlx_whisper  # type: ignore
            except ImportError as exc:  # pragma: no cover - platform specific
                raise TranscriberUnavailable(
                    "mlx-whisper is not installed. Install the [mlx] extra, or set "
                    "stt_backend = \"faster-whisper\" to transcribe on the CPU."
                ) from exc
            self._mod = mlx_whisper
        return self._mod

    def prewarm(self) -> None:
        """Load the weights and run one trivial decode, so Joel's first sentence
        of the day is not the slow one."""
        import numpy as np

        mod = self._load()
        mod.transcribe(np.zeros(16000, dtype="float32"), path_or_hf_repo=self.model,
                       fp16=True, language="en")

    def transcribe(self, audio, sample_rate: int) -> str:
        mod = self._load()
        result = mod.transcribe(audio, path_or_hf_repo=self.model, fp16=True,
                                language="en", condition_on_previous_text=False)
        return (result or {}).get("text", "")

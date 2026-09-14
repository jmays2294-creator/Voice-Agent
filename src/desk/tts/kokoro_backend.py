"""Kokoro — the opt-in quality upgrade.

Apache-2.0, and still on-device. Opt-in rather than default because its
`espeak-ng` phonemizer is GPL-3.0; it is invoked as a separate system binary
rather than linked, which is fine for an internal tool, but it is a licence
question Joel should answer deliberately rather than inherit.
"""

from __future__ import annotations

import threading

from . import VoiceUnavailable


class KokoroVoice:
    name = "kokoro"

    def __init__(self, voice_id: str = "af_heart", rate: float = 1.0) -> None:
        self.voice_id = voice_id or "af_heart"
        self.rate = rate
        self._pipeline = None
        self._stop = threading.Event()
        self._speaking = False

    def _load(self):
        if self._pipeline is None:
            try:
                from kokoro import KPipeline  # type: ignore
            except ImportError as exc:  # pragma: no cover - optional extra
                raise VoiceUnavailable(
                    "kokoro is not installed. Install the [kokoro] extra, or leave "
                    "tts_backend = \"avspeech\"."
                ) from exc
            self._pipeline = KPipeline(lang_code="a")
        return self._pipeline

    def prewarm(self) -> None:
        pipeline = self._load()
        list(pipeline(" ", voice=self.voice_id, speed=self.rate))

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        import sounddevice as sd

        pipeline = self._load()
        self._stop.clear()
        self._speaking = True
        try:
            for _, _, audio in pipeline(text, voice=self.voice_id, speed=self.rate):
                if self._stop.is_set():
                    break
                sd.play(audio, samplerate=24000, blocking=True)
        finally:
            self._speaking = False

    def stop(self) -> None:
        import sounddevice as sd

        self._stop.set()
        sd.stop()

    @property
    def speaking(self) -> bool:
        return self._speaking

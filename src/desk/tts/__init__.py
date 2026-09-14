"""Speech-out backends. On-device only.

There is no cloud option here and no flag that would add one. An unused code
path to a third party is still an audit finding, and still gets switched on by
someone in a hurry — so the path does not exist. THREAT_MODEL.md records which
vendor was considered, what it retains, and why it was cut rather than made
optional.
"""

from __future__ import annotations

from typing import Protocol


class Voice(Protocol):
    name: str

    def speak(self, text: str) -> None: ...
    def stop(self) -> None: ...
    def prewarm(self) -> None: ...
    @property
    def speaking(self) -> bool: ...


class VoiceUnavailable(RuntimeError):
    pass


def create(backend: str = "avspeech", voice: str = "", rate: float = 0.52) -> Voice:
    if backend == "avspeech":
        from .avspeech import AVSpeechVoice
        return AVSpeechVoice(voice, rate)
    if backend == "kokoro":
        from .kokoro_backend import KokoroVoice
        return KokoroVoice(voice, rate)
    raise VoiceUnavailable(
        f"unknown speech-out backend {backend!r}. Desk synthesises on-device only."
    )

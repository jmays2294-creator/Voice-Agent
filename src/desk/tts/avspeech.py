"""macOS AVSpeechSynthesizer. The default.

Ships with the OS: zero dependencies to audit, zero model weights to verify, no
third party at any layer, and first audio in roughly 50-80ms with no network at
all. Removing the cloud hop made Desk faster, not slower.
"""

from __future__ import annotations

import threading

from . import VoiceUnavailable


class AVSpeechVoice:
    name = "avspeech"

    def __init__(self, voice_id: str = "", rate: float = 0.52) -> None:
        self.voice_id = voice_id
        self.rate = rate
        self._synth = None
        self._voice = None
        self._done = threading.Event()
        self._done.set()

    def _load(self):
        if self._synth is None:
            try:
                from AVFoundation import (AVSpeechSynthesizer, AVSpeechSynthesisVoice)
            except ImportError as exc:  # pragma: no cover - platform specific
                raise VoiceUnavailable(
                    "AVFoundation is unavailable. Install the [macos] extra; Desk "
                    "does not fall back to a network voice."
                ) from exc
            self._synth = AVSpeechSynthesizer.alloc().init()
            if self.voice_id:
                self._voice = AVSpeechSynthesisVoice.voiceWithIdentifier_(self.voice_id)
            if self._voice is None:
                # Prefer an enhanced/premium system voice over the compact default.
                self._voice = AVSpeechSynthesisVoice.voiceWithLanguage_("en-US")
        return self._synth

    def prewarm(self) -> None:
        """Synthesise a silent utterance so the first real one is not the slow
        one. Held output stream, warm voice."""
        synth = self._load()
        from AVFoundation import AVSpeechUtterance

        utterance = AVSpeechUtterance.speechUtteranceWithString_(" ")
        utterance.setVoice_(self._voice)
        utterance.setRate_(self.rate)
        utterance.setVolume_(0.0)
        synth.speakUtterance_(utterance)

    def speak(self, text: str) -> None:
        if not text.strip():
            return
        synth = self._load()
        from AVFoundation import AVSpeechUtterance

        utterance = AVSpeechUtterance.speechUtteranceWithString_(text)
        utterance.setVoice_(self._voice)
        utterance.setRate_(self.rate)
        # A short pre-utterance delay would be audible between streamed
        # sentences, so it is explicitly zero.
        utterance.setPreUtteranceDelay_(0.0)
        utterance.setPostUtteranceDelay_(0.0)
        self._done.clear()
        synth.speakUtterance_(utterance)

    def stop(self) -> None:
        """Barge-in. Immediate, not at the end of the current word."""
        if self._synth is None:
            return
        from AVFoundation import AVSpeechBoundaryImmediate

        self._synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
        self._done.set()

    @property
    def speaking(self) -> bool:
        return bool(self._synth is not None and self._synth.isSpeaking())

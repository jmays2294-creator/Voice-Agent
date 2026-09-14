"""Configuration.

Values only, never credentials. Anything secret is read from the macOS keychain
at runtime by name; nothing in this repository holds one.
"""

from __future__ import annotations

import os
import platform
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import paths

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "desk.toml"


@dataclass(frozen=True)
class Latency:
    """The contract. Measured, not estimated — see BENCH.md."""
    p50_ms: int = 1200
    p95_ms: int = 1800
    transcribe_ms: int = 200
    first_token_ms: int = 600
    first_sentence_ms: int = 350
    tts_first_audio_ms: int = 80
    device_open_ms: int = 50


@dataclass(frozen=True)
class Config:
    #: Never a bare alias. The SDK resolves aliases through its bundled CLI and
    #: can quietly land on an older model; pin the full id.
    model: str = "claude-opus-5"
    stt_model: str = "mlx-community/whisper-small.en-mlx"
    stt_backend: str = "auto"          # auto | mlx | faster-whisper
    tts_backend: str = "avspeech"      # avspeech | kokoro
    tts_voice: str = "com.apple.voice.premium.en-US.Zoe"
    tts_rate: float = 0.52
    sample_rate: int = 16000
    #: Hold-to-talk key. Never a wake word, never VAD-triggered.
    ptt_keycode: int = 63              # fn
    supabase_host: str = ""            # named, not secret; see THREAT_MODEL.md
    keychain_service: str = "desk-supabase"
    session_logging: bool = False      # opt-in, 0600, gitignored, redacted
    web_grant_seconds: int = 90
    latency: Latency = field(default_factory=Latency)

    @property
    def egress_hosts(self) -> tuple[str, ...]:
        hosts = ["api.anthropic.com", "github.com"]
        if self.supabase_host:
            hosts.append(self.supabase_host)
        return tuple(hosts)


def _apply(cfg: Config, data: dict) -> Config:
    known = {f for f in Config.__dataclass_fields__ if f != "latency"}
    updates = {k: v for k, v in data.items() if k in known}
    lat = data.get("latency")
    if isinstance(lat, dict):
        fields = {k: v for k, v in lat.items() if k in Latency.__dataclass_fields__}
        updates["latency"] = replace(cfg.latency, **fields)
    return replace(cfg, **updates)


def load(path: Path | None = None) -> Config:
    cfg = Config()
    p = path or Path(os.environ.get("DESK_CONFIG", DEFAULT_CONFIG))
    if p.exists():
        with open(p, "rb") as fh:
            cfg = _apply(cfg, tomllib.load(fh))
    if os.environ.get("DESK_SUPABASE_HOST"):
        cfg = replace(cfg, supabase_host=os.environ["DESK_SUPABASE_HOST"].strip().lower())
    return cfg


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def describe_platform() -> dict:
    return {
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "apple_silicon": is_apple_silicon(),
        "state_dir": str(paths.state_dir()),
    }

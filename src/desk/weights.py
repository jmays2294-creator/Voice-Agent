"""Model-weight pinning.

The daemon downloads model weights onto a machine with repository write access
and keychain reach. A weights file that does not match its recorded hash aborts
the boot. It does not warn and continue — a warning at boot is a warning nobody
reads.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PINS = Path(__file__).resolve().parents[2] / "config" / "weights.sha256"

#: What an unfilled pin file looks like. Treated as a mismatch, so a pin file
#: nobody filled in fails loudly rather than silently accepting anything.
PLACEHOLDER = "0" * 64


class WeightsError(RuntimeError):
    """Raised instead of booting."""


@dataclass(frozen=True)
class Pin:
    sha256: str
    relative_path: str


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_pins(path: Path | None = None) -> dict[str, Pin]:
    """Parse `<sha256>  <relative/path>` lines, the sha256sum format."""
    p = path or DEFAULT_PINS
    pins: dict[str, Pin] = {}
    if not p.exists():
        return pins
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise WeightsError(f"malformed pin line: {raw!r}")
        digest, rel = parts[0].lower(), parts[1].strip().lstrip("*")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise WeightsError(f"not a sha256 digest: {digest!r}")
        pins[rel] = Pin(digest, rel)
    return pins


def verify(root: Path, pins: dict[str, Pin] | None = None,
           pin_file: Path | None = None) -> list[str]:
    """Verify every pinned file under `root`. Returns the list verified.

    Raises WeightsError — and therefore refuses the boot — on a missing pin
    file, a missing weights file, a placeholder digest, or any mismatch.
    """
    pins = pins if pins is not None else load_pins(pin_file)
    if not pins:
        raise WeightsError(
            "no model weights are pinned. Fill config/weights.sha256 with the "
            "digests printed by scripts/pin_weights.py before running Desk."
        )
    verified: list[str] = []
    for rel, pin in sorted(pins.items()):
        if pin.sha256 == PLACEHOLDER:
            raise WeightsError(
                f"{rel} still carries the placeholder digest. Pin it against the "
                f"downloaded artifact and the publisher's published digest."
            )
        target = root / rel
        if not target.exists():
            raise WeightsError(f"pinned weights file is missing: {target}")
        actual = sha256_file(target)
        if actual != pin.sha256:
            raise WeightsError(
                f"weights hash mismatch for {rel}: expected {pin.sha256}, got {actual}. "
                f"Refusing to boot."
            )
        verified.append(rel)
    return verified

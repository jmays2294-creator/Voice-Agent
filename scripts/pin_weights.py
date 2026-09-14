#!/usr/bin/env python3
"""Print SHA-256 pins for downloaded model weights.

Paste the output into config/weights.sha256, then check each digest against the
publisher's published digest before committing. Pinning what you downloaded
without checking it pins the compromise as readily as the original.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from desk.weights import sha256_file  # noqa: E402

SUFFIXES = {".npz", ".safetensors", ".bin", ".pt", ".gguf", ".json", ".model"}


def main() -> int:
    if len(sys.argv) < 2:
        print(f"usage: {sys.argv[0]} <models-dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).expanduser().resolve()
    if not root.exists():
        print(f"no such directory: {root}", file=sys.stderr)
        return 1
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES)
    if not files:
        print(f"no weight files under {root}", file=sys.stderr)
        return 1
    for p in files:
        print(f"{sha256_file(p)}  {p.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

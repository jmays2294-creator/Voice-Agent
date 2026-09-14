#!/usr/bin/env python3
"""Print SHA-256 pins for downloaded model weights.

Paste the output into config/weights.sha256, then check each digest against the
publisher's published digest before committing. Pinning what you downloaded
without checking it pins the compromise as readily as the original.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from desk.weights import sha256_file

SUFFIXES = {".npz", ".safetensors", ".bin", ".pt", ".gguf", ".json", ".model"}


PIN_FILE = Path(__file__).resolve().parents[1] / "config" / "weights.sha256"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("models_dir", help="the directory Desk verifies, e.g. ~/.desk/models")
    ap.add_argument("--write", action="store_true",
                    help="write the digests into config/weights.sha256 instead of "
                         "printing them for you to copy")
    args = ap.parse_args()

    root = Path(args.models_dir).expanduser().resolve()
    if not root.exists():
        print(f"no such directory: {root}", file=sys.stderr)
        return 1
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in SUFFIXES)
    if not files:
        print(f"no weight files under {root}", file=sys.stderr)
        return 1

    digests = {str(p.relative_to(root)): sha256_file(p) for p in files}

    if not args.write:
        for rel, digest in digests.items():
            print(f"{digest}  {rel}")
        print(f"\nNothing was written. Re-run with --write to put these into "
              f"{PIN_FILE.name}.", file=sys.stderr)
        return 0

    # Replace the digest on each declared line, matching by path. Deliberately
    # does NOT add lines: the pin file is the list of files Desk requires, and
    # growing it from whatever happens to be on disk would let an extra file
    # pin itself into the boot gate.
    lines = PIN_FILE.read_text().splitlines()
    declared, written, missing = set(), [], []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        rel = parts[1].strip().lstrip("*")
        declared.add(rel)
        if rel in digests:
            lines[i] = f"{digests[rel]}  {rel}"
            written.append(rel)
        else:
            missing.append(rel)

    if missing:
        print(f"{PIN_FILE.name} requires files that are not in {root}:", file=sys.stderr)
        for rel in missing:
            print(f"  missing: {rel}", file=sys.stderr)
        print("Nothing was written.", file=sys.stderr)
        return 1

    extra = sorted(set(digests) - declared)
    PIN_FILE.write_text("\n".join(lines) + "\n")

    for rel in written:
        print(f"pinned  {digests[rel]}  {rel}")
    for rel in extra:
        print(f"ignored {rel} (not declared in {PIN_FILE.name})")
    print(f"\nWrote {len(written)} digest(s) to {PIN_FILE.name}.")
    print("Now check each one against the publisher's published digest before you "
          "commit it. Pinning what you downloaded without checking it pins the "
          "compromise exactly as readily as the original.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

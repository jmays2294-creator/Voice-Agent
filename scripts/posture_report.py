#!/usr/bin/env python3
"""Report Joel's Claude Code account posture. Reports — never changes.

Phase 0 asks for two things in THREAT_MODEL.md: whether Claude Code runs under
consumer (Pro/Max) or commercial terms, and the value of cleanupPeriodDays.
Both are account settings, and both are his call.

Run this on the Mac. A cloud session cannot answer for the Mac.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SAFE_KEYS = {"organizationRole", "workspaceRole", "organizationName",
             "accountUuid", "organizationUuid", "emailAddress"}


def main() -> int:
    home = Path(os.path.expanduser("~"))
    cfg = home / ".claude.json"
    print("Claude Code account posture\n" + "=" * 34)
    if not cfg.exists():
        print(f"  no config at {cfg} — is Claude Code installed for this user?")
        return 1

    data = json.loads(cfg.read_text())
    account = data.get("oauthAccount") or {}

    print("\nAccount")
    for key in sorted(SAFE_KEYS & set(account)):
        print(f"  {key:20s} {account[key]}")
    for key in sorted(set(account) - SAFE_KEYS):
        print(f"  {key:20s} <present, not printed>")

    print("\nTier")
    role = account.get("organizationRole") or account.get("workspaceRole")
    org = account.get("organizationName")
    if role or org:
        print(f"  organization role   {role or '(none)'}")
        print(f"  organization        {org or '(none)'}")
        print("  -> an organization implies commercial terms. Confirm in the console.")
    else:
        print("  no organization role is recorded locally.")
        print("  -> this looks like CONSUMER (Pro/Max) terms. Confirm at claude.ai.")
    print("  Consumer and commercial terms differ on whether conversation content")
    print("  may be used for training. Desk's conversations are Comp Desk material")
    print("  and sometimes client material under RPC 1.6. If this reports consumer,")
    print("  move Desk to commercial terms before Phase 5.")

    print("\nLocal transcript retention")
    cleanup = data.get("cleanupPeriodDays", "<unset>")
    print(f"  cleanupPeriodDays   {cleanup}")
    if cleanup == "<unset>":
        print("  -> UNSET, so the default window applies. Claude Code writes session")
        print("     transcripts under ~/.claude/projects/ regardless of Desk keeping")
        print("     its own in memory. Set this explicitly and low.")

    projects = home / ".claude" / "projects"
    if projects.exists():
        files = list(projects.rglob("*.jsonl"))
        size = sum(f.stat().st_size for f in files)
        print(f"  transcripts on disk {len(files)} files, {size/1e6:.1f} MB")

    print("\nSecrets directory")
    secrets = home / "TheCompDesk-Secrets"
    if secrets.exists():
        n = len([p for p in secrets.rglob("*") if p.is_file()])
        print(f"  {n} files in plaintext. Desk never reads this directory, but it")
        print("  belongs in the keychain or a password manager.")
    else:
        print("  not present on this machine.")

    print("\nNothing above was changed. These are Joel's decisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

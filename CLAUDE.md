# Voice-Agent

This is Desk: an on-device voice agent for Joel's Comp Desk OS. A
permission-bypassed Claude session holds real tool access, made survivable by a
`PreToolUse` guard, speaking and listening entirely on-device.

This file is project instructions for a coding session working in this
repository. It is not Desk's persona — that is `prompts/desk.md`, loaded at
runtime as the voice session's system prompt. Keep the two separate: this file
is read by an engineer's tools, that one is read out loud through a speaker.

Read `README.md`, `THREAT_MODEL.md` and `ACCEPTANCE.md` before making a
non-trivial change. They are the brief.

## Running the checks

```sh
python3 -m pytest tests/ -q
python3 -m ruff check src/ tests/ scripts/
```

Both must be green before anything is pushed. There is no partial credit.

`tests/test_guard_injection.py` and `tests/test_never.py` encode the threat
model — a real prompt injection attempt run through the actual guard process,
and the Never list (no wake word, no cloud voice, no raw audio persisted, no
egress from anything that touches speech, and more) asserted against the
committed tree. Red there is a stop, never a flake, and never something to
work around.

## The guard is the security boundary, not this file

The voice session runs with `permission_mode="bypassPermissions"`, because a
permission prompt is fatal to a voice loop. That means `src/desk/guard/` — a
`PreToolUse` hook that sees the tool call and never the tool result — decides
what happens, not the system prompt and not this file. See `THREAT_MODEL.md`
for why a persona-file instruction can never be the boundary against an
injected one.

## High-risk paths

These paths are `risk_class='high'` in the planning loop, and for the same
reason here: a change to any of them changes what the guard permits.

```
src/desk/guard/**          config/weights.sha256
config/pf/**               CLAUDE.md
config/desk.toml (egress, model, stt/tts backend keys)
```

A change touching one of these never auto-ships. State in one sentence what it
newly permits that was refused before — if you cannot, you do not understand
it well enough to have made it.

## Conventions

- Comment *why*, not *what*. A well-named function does not need a comment
  restating its name in prose.
- No absolute home paths, anywhere, ever. Every path is derived at runtime
  through `src/desk/paths.py` so a clone on another Mac works unchanged.
  `tests/test_never.py` scans the whole tracked tree for this and has no
  exception list.
- No secret values committed, for the same reason and the same enforcement.
  Secrets are read from the macOS keychain by name at runtime.
- New behaviour needs a test that would have failed before it existed.
- Never merge to `main`, deploy, or push anywhere but a feature branch from an
  automated loop — see `ops/loops/README.md` for what each loop may write.

"""The write allowlist.

Every mutation Desk can perform is an entry in ACTIONS. There is no other write
path: the guard denies arbitrary Bash, so a capability that is not named here
does not exist, whatever the model decides it wants.

This module is pure data + validation. It imports nothing but the stdlib so it
can be loaded by the guard hook on the latency path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

# Risk classes are spoken back to Joel before a confirmation is accepted.
RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

# --- parameter validators -------------------------------------------------

_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_UUID = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
_LANE = re.compile(r"\A[a-z][a-z0-9_-]{0,31}\Z")
#: Identifiers that *look* valid but mean "everything". An injection that asks
#: to approve `ALL` must not get a syntactically-acceptable wildcard through.
#: The executor also resolves every id against the real queue; this is the
#: cheaper half of that pair, and it refuses before anything is looked up.
_RESERVED_IDS = frozenset({
    "all", "any", "every", "everything", "each", "none", "null", "nil",
    "undefined", "true", "false", "star", "wildcard", "default", "latest",
    "head", "main", "master", "prod", "production", "*", "%", "-",
})
_SLUG = re.compile(r"\A[a-z][a-z0-9_.-]{0,63}\Z")
_WINDOW = re.compile(r"\A(?:[1-9][0-9]{0,2}h|[1-9][0-9]{0,2}d|today|overnight|week)\Z")
# Free text: printable, no control characters, no newlines, bounded.
_TEXT = re.compile(r"\A[^\x00-\x1f\x7f]{1,600}\Z")


def _ident(v: str) -> bool:
    if v.lower() in _RESERVED_IDS:
        return False
    return bool(_ID.match(v) or _UUID.match(v))


def _lane(v: str) -> bool:
    if v.lower() in _RESERVED_IDS:
        return False
    return bool(_LANE.match(v))


def _slug(v: str) -> bool:
    if v.lower() in _RESERVED_IDS:
        return False
    return bool(_SLUG.match(v))


def _window(v: str) -> bool:
    return bool(_WINDOW.match(v))


def _text(v: str) -> bool:
    return bool(_TEXT.match(v))


@dataclass(frozen=True)
class Param:
    name: str
    check: Callable[[str], bool]
    required: bool = True


@dataclass(frozen=True)
class Action:
    name: str
    risk: str
    writes: bool
    summary: str
    positional: tuple[Param, ...] = ()
    flags: dict[str, Param] = field(default_factory=dict)
    # Write actions require an explicit spoken confirm word; see Rule 7.
    needs_confirm: bool = False

    def validate(self, argv: list[str]) -> str | None:
        """Return None if argv is acceptable, else a human reason for denial."""
        pos: list[str] = []
        flags: dict[str, str] = {}
        i = 0
        while i < len(argv):
            tok = argv[i]
            if tok.startswith("--"):
                key = tok[2:]
                if key not in self.flags:
                    return f"unknown option --{key} for action {self.name}"
                if i + 1 >= len(argv):
                    return f"option --{key} is missing its value"
                if key in flags:
                    return f"option --{key} given twice"
                flags[key] = argv[i + 1]
                i += 2
                continue
            if tok.startswith("-") and tok != "-":
                return f"short options are not accepted ({tok})"
            pos.append(tok)
            i += 1

        required_pos = [p for p in self.positional if p.required]
        if len(pos) < len(required_pos):
            return f"action {self.name} needs {len(required_pos)} argument(s), got {len(pos)}"
        if len(pos) > len(self.positional):
            return f"action {self.name} takes at most {len(self.positional)} argument(s)"
        for spec, value in zip(self.positional, pos):
            if not spec.check(value):
                return f"argument {spec.name} is not a valid value"

        for key, spec in self.flags.items():
            if spec.required and key not in flags:
                return f"action {self.name} requires --{key}"
        for key, value in flags.items():
            if not self.flags[key].check(value):
                return f"option --{key} is not a valid value"

        if self.needs_confirm and "confirm" not in flags:
            return f"action {self.name} is risk {self.risk} and requires an explicit confirmation"
        return None


_CONFIRM = Param("confirm", lambda v: bool(re.match(r"\A[a-z]{3,16}\Z", v)))
_PAYLOAD = Param("payload", _slug, required=False)

# --- the allowlist --------------------------------------------------------
# Reads are wide but still enumerated: each one is a parameterised query the
# daemon owns, never SQL the model composes.

_ALL: tuple[Action, ...] = (
    # ---- read -------------------------------------------------------------
    Action("loop.status", RISK_LOW, False,
           "Loop runs in a window: pass, fail, and rows still marked running.",
           positional=(Param("window", _window, required=False),)),
    Action("loop.failures", RISK_LOW, False,
           "Failed and silently-failed loop runs, with the four known modes checked.",
           positional=(Param("window", _window, required=False),)),
    Action("lane.status", RISK_LOW, False,
           "State of one build lane, including claim age.",
           positional=(Param("lane", _lane),)),
    Action("lane.why", RISK_LOW, False,
           "Why a lane failed: exit reason and the tail of its recorded error.",
           positional=(Param("lane", _lane),)),
    Action("sweep.status", RISK_LOW, False,
           "Most recent app and workspace sweep runs and their verdicts.",
           positional=(Param("target", _slug, required=False),)),
    Action("queue.list", RISK_LOW, False,
           "Items waiting on Joel, newest first.",
           positional=(Param("queue", _slug, required=False),)),
    Action("queue.show", RISK_LOW, False,
           "One queue item in full, with its risk class.",
           positional=(Param("id", _ident),)),
    Action("owner.requests", RISK_LOW, False, "Open owner requests and reminders."),
    Action("health.check", RISK_LOW, False, "Daemon self-check: interlock, mic, egress, latency."),
    Action("audit.recent", RISK_LOW, False,
           "Recent voice audit rows, including denials.",
           positional=(Param("window", _window, required=False),)),

    # ---- write ------------------------------------------------------------
    Action("queue.approve", RISK_HIGH, True,
           "Approve one queue item.",
           positional=(Param("id", _ident),),
           flags={"confirm": _CONFIRM}, needs_confirm=True),
    Action("queue.reject", RISK_MEDIUM, True,
           "Reject one queue item.",
           positional=(Param("id", _ident),),
           flags={"confirm": _CONFIRM}, needs_confirm=True),
    Action("queue.defer", RISK_LOW, True,
           "Defer one queue item.",
           positional=(Param("id", _ident),),
           flags={"confirm": _CONFIRM}, needs_confirm=True),
    Action("sweep.trigger", RISK_MEDIUM, True,
           "Start a sweep.",
           positional=(Param("target", _slug),),
           flags={"confirm": _CONFIRM}, needs_confirm=True),
    Action("lane.kick", RISK_MEDIUM, True,
           "Re-run one build lane.",
           positional=(Param("lane", _lane),),
           flags={"confirm": _CONFIRM}, needs_confirm=True),
    Action("note.write", RISK_LOW, True,
           "Write a note for Joel.",
           flags={"text": Param("text", _text, required=False), "payload": _PAYLOAD}),
    Action("reminder.add", RISK_LOW, True,
           "Add an owner reminder.",
           flags={"text": Param("text", _text, required=False), "payload": _PAYLOAD}),
)

ACTIONS: dict[str, Action] = {a.name: a for a in _ALL}
READ_ACTIONS = frozenset(a.name for a in _ALL if not a.writes)
WRITE_ACTIONS = frozenset(a.name for a in _ALL if a.writes)

#: argv[0] the guard will accept. Bare name only — no path, no interpreter.
ACTION_BINARY = "desk-action"

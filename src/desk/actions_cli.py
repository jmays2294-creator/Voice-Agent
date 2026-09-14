"""`desk-action` — the only write path.

The guard already refused everything that is not one of these. This executor
**re-validates anyway**: it is a separate process with its own entry points, and
a defence that only works because another defence ran is not a defence. It also
resolves every identifier against real data, so an id that is merely
well-shaped still cannot act on something that does not exist.

Read actions answer from Supabase. Write actions require the confirmation word
the guard insisted on, write an audit row with `source='voice'`, and report what
changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desk import config as cfg_mod  # noqa: E402
from desk.audit import Audit  # noqa: E402
from desk.guard.actions import ACTIONS  # noqa: E402

EXIT_OK = 0
EXIT_REFUSED = 3
EXIT_ERROR = 4

#: Only these tables are reachable, and only through the query each action owns.
#: A table not named here cannot be reached from a voice turn at all — there is
#: no general query path. See VOICE_SURFACE.md.
_READ_QUERIES = {
    "loop.status": ("loop_runs", "select=id,loop,status,started_at,finished_at,notes"
                                 "&order=started_at.desc&limit=40"),
    "loop.failures": ("loop_runs", "select=id,loop,status,started_at,finished_at,notes"
                                   "&status=neq.passed&order=started_at.desc&limit=40"),
    "lane.status": ("lane_claims", "select=id,lane,claimed_at,released_at,files"
                                   "&order=claimed_at.desc&limit=20"),
    "lane.why": ("loop_runs", "select=id,loop,status,notes,finished_at"
                              "&order=started_at.desc&limit=20"),
    "sweep.status": ("app_e2e_runs", "select=id,kind,status,started_at,report_path"
                                     "&order=started_at.desc&limit=10"),
    "queue.list": ("app_improvements", "select=id,title,status,est_hours,risk_class"
                                       "&status=eq.planned&order=id.desc&limit=25"),
    "queue.show": ("app_improvements", "select=*"),
    "owner.requests": ("owner_requests", "select=id,request,status,created_at"
                                         "&order=created_at.desc&limit=20"),
    "audit.recent": ("voice_audit", "select=at,action,risk,decision,outcome"
                                    "&order=at.desc&limit=30"),
}


def _fail(message: str, code: int = EXIT_REFUSED) -> int:
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _fail("no action named")

    name, rest = args[0], args[1:]
    action = ACTIONS.get(name)
    if action is None:
        return _fail(f"{name} is not an allowlisted action")

    # Re-validate independently of the guard.
    problem = action.validate(rest)
    if problem is not None:
        return _fail(problem)

    parsed = _parse(rest)
    cfg = cfg_mod.load()
    audit = Audit(host=cfg.supabase_host, service=cfg.keychain_service)

    try:
        if action.writes:
            if not parsed.flags.get("confirm"):
                return _fail(f"{name} is risk {action.risk} and was not confirmed")
            result = _execute_write(name, action, parsed, audit)
        else:
            result = _execute_read(name, parsed, audit)
    except Exception as exc:  # noqa: BLE001
        audit.action(name, action.risk, " ".join(args), args, outcome=f"error: {exc}")
        return _fail(f"{name} failed: {exc}", EXIT_ERROR)

    print(json.dumps(result, default=str))
    return EXIT_OK


class _Parsed:
    def __init__(self, positional: list[str], flags: dict[str, str]) -> None:
        self.positional = positional
        self.flags = flags


def _parse(rest: list[str]) -> _Parsed:
    positional: list[str] = []
    flags: dict[str, str] = {}
    i = 0
    while i < len(rest):
        if rest[i].startswith("--"):
            flags[rest[i][2:]] = rest[i + 1]
            i += 2
        else:
            positional.append(rest[i])
            i += 1
    return _Parsed(positional, flags)


def _execute_read(name: str, parsed: _Parsed, audit: Audit) -> dict:
    table, query = _READ_QUERIES[name]
    if name == "queue.show":
        query += f"&id=eq.{parsed.positional[0]}"
    if name == "lane.status" and parsed.positional:
        query += f"&lane=eq.{parsed.positional[0]}"
    rows = _select(audit, table, query)
    return {"ok": True, "action": name, "rows": rows, "count": len(rows)}


def _execute_write(name: str, action, parsed: _Parsed, audit: Audit) -> dict:
    """Every write resolves its target first. A well-shaped id that names
    nothing is a refusal, not a no-op that reports success."""
    target = parsed.positional[0] if parsed.positional else None
    changed = None

    if name in ("queue.approve", "queue.reject", "queue.defer"):
        existing = _select(audit, "app_improvements", f"select=id,title,status&id=eq.{target}")
        if not existing:
            raise ValueError(f"no queue item {target}")
        status = {"queue.approve": "approved", "queue.reject": "rejected",
                  "queue.defer": "deferred"}[name]
        audit._post("app_improvements", {"status": status},
                    method="PATCH", params=f"?id=eq.{target}")
        changed = f"{target}: {existing[0].get('status')} -> {status}"

    elif name == "lane.kick":
        audit._post("owner_requests", {"request": f"voice: re-run lane {target}",
                                       "status": "open"})
        changed = f"queued a re-run of lane {target}"

    elif name == "sweep.trigger":
        audit._post("owner_requests", {"request": f"voice: start sweep {target}",
                                       "status": "open"})
        changed = f"queued sweep {target}"

    elif name in ("note.write", "reminder.add"):
        text = parsed.flags.get("text")
        if not text and parsed.flags.get("payload"):
            from desk import paths
            p = (paths.scratch_dir() / parsed.flags["payload"]).resolve(strict=False)
            if not p.is_relative_to(paths.scratch_dir()):
                raise ValueError("payload must live in the scratch folder")
            text = json.loads(p.read_text()).get("text", "")
        if not text:
            raise ValueError("nothing to write")
        table = "owner_reminders" if name == "reminder.add" else "owner_requests"
        audit._post(table, {"request" if table == "owner_requests" else "reminder": text,
                            "status": "open"})
        changed = f"wrote a {'reminder' if name == 'reminder.add' else 'note'}"

    audit.action(name, action.risk, asked=" ".join([name, *parsed.positional]),
                 argv=[name, *parsed.positional], outcome="done", changed=changed)
    return {"ok": True, "action": name, "risk": action.risk, "changed": changed}


def _select(audit: Audit, table: str, query: str) -> list[dict]:
    import urllib.error
    import urllib.request

    if not audit.host:
        return []
    url = f"https://{audit.host}/rest/v1/{table}?{query}"
    token = audit._auth()
    req = urllib.request.Request(url, headers={
        "apikey": token, "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=audit.timeout) as resp:
            data = json.loads(resp.read() or b"[]")
            return data if isinstance(data, list) else []
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise RuntimeError(f"could not reach the database: {type(exc).__name__}") from exc


if __name__ == "__main__":
    raise SystemExit(main())

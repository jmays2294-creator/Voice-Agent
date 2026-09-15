"""Audit and the dashboard feed.

Two properties matter here. Rule 7: every permitted action is reconstructable,
reads included. Rule 4: the latency feed carries numbers and nothing else.
"""
import json
from pathlib import Path

import pytest

from desk import paths
from desk.audit import Audit


@pytest.fixture
def audit(sandbox):
    paths.ensure_dirs()
    # No host: every row spools to disk, which is exactly the offline path and
    # lets the tests read back precisely what would have been sent.
    return Audit(host="")


def spooled(sandbox):
    p = sandbox.state / "log" / "audit-spool.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


# --- latency feed ---------------------------------------------------------

def test_a_turn_row_carries_only_numbers_and_booleans(audit, sandbox):
    audit.turn(total_ms=940.6, release_to_text_ms=180.2, first_token_ms=420.9,
               first_sentence_ms=690.1, first_audio_ms=770.4, sentences=3,
               tool_calls=1, barge_in=False, rebuilt=False)
    rows = spooled(sandbox)
    assert len(rows) == 1 and rows[0]["table"] == "voice_turns"
    row = rows[0]["row"]
    for key, value in row.items():
        if key in ("at", "run_id"):
            continue
        assert isinstance(value, (int, float, bool)) or value is None, \
            f"voice_turns.{key} carried {type(value).__name__}: {value!r}"


def test_turn_timings_are_rounded_to_whole_milliseconds(audit, sandbox):
    audit.turn(total_ms=940.6, first_token_ms=420.4)
    row = spooled(sandbox)[0]["row"]
    assert row["total_ms"] == 941
    assert row["first_token_ms"] == 420


def test_a_negative_timing_never_reaches_the_row(audit, sandbox):
    """first_audio - first_sentence can go negative on a clock hiccup, and the
    table's check constraint would reject the whole row."""
    audit.turn(total_ms=900, first_audio_ms=-5)
    row = spooled(sandbox)[0]["row"]
    assert row["first_audio_ms"] == 0
    assert row["total_ms"] >= 0


def test_absent_stages_stay_null_rather_than_zero(audit, sandbox):
    """A stage that did not happen is unknown, not instant. Zero-filling would
    quietly drag the percentiles down and make the contract look met."""
    audit.turn(total_ms=900)
    row = spooled(sandbox)[0]["row"]
    assert row["first_token_ms"] is None
    assert row["first_audio_ms"] is None


def test_barge_in_and_rebuild_are_recorded(audit, sandbox):
    audit.turn(total_ms=120, barge_in=True, rebuilt=True)
    row = spooled(sandbox)[0]["row"]
    assert row["barge_in"] is True and row["rebuilt"] is True


# --- Rule 7 ---------------------------------------------------------------

def test_an_action_row_records_what_ran_and_what_changed(audit, sandbox):
    audit.action("queue.approve", "high", asked="queue.approve item-12",
                 argv=["queue.approve", "item-12"], outcome="done",
                 changed="item-12: planned -> approved")
    row = spooled(sandbox)[0]["row"]
    assert row["source"] == "voice" and row["decision"] == "allow"
    assert row["action"] == "queue.approve" and row["risk"] == "high"
    assert "approved" in row["changed"]


def test_a_denial_row_records_the_rule_and_that_it_was_spoken(audit, sandbox):
    audit.denial("Bash", "bash.forbidden_verb", "git is not something the voice "
                 "session may run.", spoken=True)
    row = spooled(sandbox)[0]["row"]
    assert row["decision"] == "deny" and row["outcome"] == "bash.forbidden_verb"
    assert row["spoken_aloud"] is True


def test_reads_are_audited_too(sandbox, monkeypatch):
    """A read is how a case number reaches a room. "It only looked" is not a
    reason to leave it unreconstructable."""
    import desk.actions_cli as cli

    paths.ensure_dirs()
    monkeypatch.setattr(cli, "_select", lambda a, t, q: [{"id": "item-12"}])
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    assert cli.main(["queue.show", "item-12"]) == 0
    rows = [r for r in spooled(sandbox) if r["table"] == "voice_audit"]
    assert rows, "a permitted read wrote no audit row"
    assert rows[-1]["row"]["action"] == "queue.show"
    assert rows[-1]["row"]["decision"] == "allow"


# --- redaction ------------------------------------------------------------

def test_a_note_body_never_reaches_an_audit_row(sandbox, monkeypatch):
    """The first line of defence, and the one that actually holds.

    Redacting an arbitrary person's name out of free text is not reliably
    possible — "Jane Roe" and "Lane Kick" are the same shape. So a note's body
    goes only to the table Joel reads it from; the audit row records that a
    note was written, never what it said.
    """
    import desk.actions_cli as cli

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    dictated = "call Jane Roe back about the Kowalski hearing on the third"
    assert cli.main(["note.write", "--text", dictated]) == 0

    rows = [r for r in spooled(sandbox) if r["table"] == "voice_audit"]
    assert rows, "the note wrote no audit row"
    body = json.dumps(rows)
    assert "Jane Roe" not in body
    assert "Kowalski" not in body
    assert rows[-1]["row"]["changed"] == "wrote a note"


def test_a_screen_write_never_puts_its_text_in_an_audit_row(sandbox, monkeypatch):
    """BLOCKING FINDING B1 from the bounced first attempt: it audited
    argv=[name, '--text', text], putting the very detail Rule 4.5 exists to
    keep off the spoken/logged channel into voice_audit. screen.write must
    follow the same shape as note.write: argv is the action name alone."""
    import desk.actions_cli as cli

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    privileged = "claimant Jane Roe, WCB G1234567"
    assert cli.main(["screen.write", "--text", privileged]) == 0

    rows = [r for r in spooled(sandbox) if r["table"] == "voice_audit"]
    assert rows, "screen.write wrote no audit row"
    row = rows[-1]["row"]
    assert row["argv"] == ["screen.write"]
    assert row["asked"] == "screen.write"
    body = json.dumps(rows)
    assert "Jane Roe" not in body
    assert "G1234567" not in body
    assert row["changed"] == "wrote to the screen"


def test_screen_write_actually_lands_on_the_screen(sandbox, monkeypatch):
    """The executor re-validates and executes independently of the guard —
    prove the text it was given actually reaches the file, sanitised."""
    import desk.actions_cli as cli
    from desk.screen import Screen

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    assert cli.main(["screen.write", "--text", "G1234567 hearing on the third"]) == 0
    assert Screen().read() == "G1234567 hearing on the third"


def test_audit_rows_are_built_from_the_action_not_from_free_text(sandbox, monkeypatch):
    """`asked` is the action and its validated arguments. Those cannot contain
    a space, so a dictated sentence has no route into the field."""
    import desk.actions_cli as cli

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    monkeypatch.setattr(cli, "_select", lambda a, t, q: [{"id": "item-12",
                                                          "status": "planned"}])
    assert cli.main(["queue.approve", "item-12", "--confirm", "approve"]) == 0
    row = [r for r in spooled(sandbox) if r["table"] == "voice_audit"][-1]["row"]
    assert row["asked"] == "queue.approve item-12"
    assert row["argv"] == ["queue.approve", "item-12"]


def test_case_material_is_redacted_if_it_ever_does_reach_a_row(audit, sandbox):
    """The second line. Not relied on for names, but it must still work."""
    audit.action("note.write", "low",
                 asked="note.write claimant Jane Roe WCB G1234567",
                 argv=["note.write"], outcome="done",
                 changed="approved for claimant Jane Roe, case G1234567")
    body = json.dumps(spooled(sandbox))
    assert "G1234567" not in body
    assert "Jane Roe" not in body


def test_a_credential_never_reaches_a_row(audit, sandbox):
    # Assembled from parts: the tree-wide secret scan has no exception list, and
    # a test fixture is not a reason to start one.
    fake = "sk" + "-" + "abcdefghijklmnopqrstuvwx"
    audit.action("note.write", "low", asked=f"note.write {fake}",
                 argv=["note.write"], outcome="done")
    body = json.dumps(spooled(sandbox))
    assert fake not in body


# --- offline --------------------------------------------------------------

def test_network_loss_queues_rather_than_dropping(audit, sandbox):
    """Rule 7 does not get suspended because the wifi dropped."""
    for i in range(3):
        audit.turn(total_ms=900 + i)
    assert len(spooled(sandbox)) == 3


def test_the_spool_is_owner_only(audit, sandbox):
    audit.turn(total_ms=900)
    p = sandbox.state / "log" / "audit-spool.jsonl"
    assert oct(p.stat().st_mode)[-3:] == "600"


# --- the allowlist and the executor must not drift ------------------------

def test_every_allowlisted_action_is_actually_executable(sandbox, monkeypatch):
    """A guard that permits an action the executor refuses is a dead entry that
    reads as a capability. This catches that divergence permanently."""
    import desk.actions_cli as cli
    from desk.guard.actions import ACTIONS

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    monkeypatch.setattr(cli, "_select", lambda a, t, q: [{"id": "item-12",
                                                          "status": "planned"}])
    sample = {"window": "24h", "lane": "lane-a", "id": "item-12", "target": "app",
              "queue": "app"}
    dead = []
    for name, action in ACTIONS.items():
        argv = [name]
        for spec in action.positional:
            if spec.required:
                argv.append(sample[spec.name])
        for key, spec in action.flags.items():
            if spec.required or key == "confirm":
                argv += [f"--{key}", "approve" if key == "confirm" else "a note"]
        if name in ("note.write", "reminder.add"):
            argv += ["--text", "a note"]
        code = cli.main(argv)
        if code != 0:
            dead.append(f"{name} -> exit {code}")
    assert dead == [], dead


def test_a_write_that_declares_a_confirmation_still_demands_one(sandbox, monkeypatch):
    import desk.actions_cli as cli

    paths.ensure_dirs()
    monkeypatch.setattr(cli.cfg_mod, "load", lambda: cli.cfg_mod.Config(supabase_host=""))
    assert cli.main(["queue.approve", "item-12"]) != 0


# --- the live schema, pinned -------------------------------------------------
# Read off the real public.loop_runs on 2026-09-14. Three bugs shipped past code
# review because nothing here was checked against it: a `source` column that
# does not exist, and status values of passed/failed where the table uses
# pass/fail/noop/partial. Every one of them would have 400'd on the first
# session and — before the dead-letter handling — spooled forever, looking
# exactly like a daemon nobody had spoken to.

LOOP_RUNS_COLUMNS = {
    "id", "loop", "dept", "started_at", "finished_at", "status", "items_in",
    "items_out", "gate_failures", "notes", "error", "session_url", "host",
    "created_at", "routine",
}
LOOP_RUNS_STATUSES = {"running", "pass", "fail", "noop", "partial"}


def _posted(audit, sandbox, table):
    return [r["row"] for r in spooled(sandbox) if r["table"] == table]


def test_session_rows_use_only_columns_that_exist(audit, sandbox):
    audit.start_session()
    audit.end_session(turns=4, actions=2)
    rows = _posted(audit, sandbox, "loop_runs")
    assert rows, "no loop_runs row was written"
    for row in rows:
        unknown = set(row) - LOOP_RUNS_COLUMNS
        assert not unknown, f"loop_runs has no column(s): {sorted(unknown)}"


def test_session_rows_use_the_real_status_vocabulary(audit, sandbox):
    audit.start_session()
    audit.end_session(turns=4, actions=2)
    for row in _posted(audit, sandbox, "loop_runs"):
        assert row["status"] in LOOP_RUNS_STATUSES, f"unknown status {row['status']!r}"


@pytest.mark.parametrize("turns,error,expected", [
    (4, None, "pass"),
    (0, None, "noop"),     # ran and did nothing != answered nine questions
    (4, "boom", "fail"),
    (0, "boom", "fail"),
])
def test_session_status_reflects_what_actually_happened(audit, sandbox, turns, error, expected):
    audit.start_session()
    audit.end_session(turns=turns, error=error, actions=0)
    assert _posted(audit, sandbox, "loop_runs")[-1]["status"] == expected


def test_an_error_goes_to_the_error_column_not_the_notes(audit, sandbox):
    audit.start_session()
    audit.end_session(turns=1, error="the transcriber died")
    row = _posted(audit, sandbox, "loop_runs")[-1]
    assert "transcriber" in row["error"]
    assert "transcriber" not in (row["notes"] or "")


def test_the_daemon_identifies_itself_as_a_mac_loop(audit, sandbox):
    audit.start_session()
    row = _posted(audit, sandbox, "loop_runs")[0]
    assert row["loop"] == "mac-desk-voice" and row["host"] == "mac"


def test_the_dashboard_rpc_queries_the_same_loop_name():
    """The daemon writing one name and the dashboard reading another is a whole
    screen of zeros and no error anywhere."""
    from desk.audit import LOOP_NAME
    sql = (Path(__file__).resolve().parents[1]
           / "sql" / "002_voice_turns_and_dashboard.sql").read_text()
    assert f"loop = '{LOOP_NAME}'" in sql
    # The JSON output keys are `passed`/`failed` — that is the dashboard's
    # vocabulary and it is fine. What must not appear is a COMPARISON against
    # a status value the table never stores.
    import re
    for bad in re.finditer(r"status\s*(?:=|in)\s*\(?\s*'(\w+)'", sql):
        assert bad.group(1) in LOOP_RUNS_STATUSES, \
            f"the RPC filters on status {bad.group(1)!r}, which loop_runs never stores"


# --- a rejected row is loud, not queued -------------------------------------

def _http_error(code, body=b'{"message":"column does not exist"}'):
    import io
    import urllib.error
    return urllib.error.HTTPError("https://h/rest/v1/x", code, "Bad Request",
                                  {}, io.BytesIO(body))


def test_a_rejected_row_is_dead_lettered_never_retried(sandbox, monkeypatch):
    """A 400 will be a 400 forever. Spooling it retries it every boot and looks
    exactly like a quiet daemon."""
    from desk import audit as audit_mod

    paths.ensure_dirs()
    a = audit_mod.Audit(host="proj.supabase.co")
    monkeypatch.setenv("DESK_SUPABASE_KEY", "not-a-real-key")
    monkeypatch.setattr(audit_mod, "open_https",
                        lambda req, timeout: (_ for _ in ()).throw(_http_error(400)))
    a.start_session()

    assert spooled(sandbox) == [], "a rejected row was queued for retry"
    dead = paths.dead_letter()
    assert dead.exists(), "a rejected row vanished"
    rec = json.loads(dead.read_text().splitlines()[0])
    assert rec["status"] == 400 and rec["table"] == "loop_runs"
    assert oct(dead.stat().st_mode)[-3:] == "600"


def test_a_transient_failure_is_still_queued(sandbox, monkeypatch):
    from desk import audit as audit_mod

    paths.ensure_dirs()
    a = audit_mod.Audit(host="proj.supabase.co")
    monkeypatch.setenv("DESK_SUPABASE_KEY", "not-a-real-key")
    monkeypatch.setattr(audit_mod, "open_https",
                        lambda req, timeout: (_ for _ in ()).throw(_http_error(503)))
    a.start_session()
    assert spooled(sandbox), "a 503 should queue for retry"
    assert not paths.dead_letter().exists()


def test_health_reports_rejected_rows_as_a_failure(sandbox):
    from desk import health

    paths.ensure_dirs()
    report = health.Report()
    health.check_hygiene(report)
    assert any(c.verdict == health.PASS and "refused" in c.name for c in report.checks)

    paths.dead_letter().write_text(json.dumps({"table": "loop_runs"}) + "\n")
    report = health.Report()
    health.check_hygiene(report)
    bad = [c for c in report.checks if c.verdict == health.FAIL]
    assert bad and "refused" in bad[0].name

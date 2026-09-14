"""Audit and the dashboard feed.

Two properties matter here. Rule 7: every permitted action is reconstructable,
reads included. Rule 4: the latency feed carries numbers and nothing else.
"""
import json

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
    audit.action("note.write", "low", asked="note.write sk-abcdefghijklmnopqrstuvwx",
                 argv=["note.write"], outcome="done")
    body = json.dumps(spooled(sandbox))
    assert "sk-abcdefghijklmnopqrstuvwx" not in body


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

"""The queue contract, asserted rather than trusted.

Work in this department has twice become invisible to every queue while every
loop reported healthy. Both times the rule that decided what got reviewed was
prose in a routine document, and both times a copy of it drifted:

  - `status='implemented' AND gate_b='pending'` missed a rebuilt item that
    still carried the previous commit's 'fail'. A P0 guard change went
    unreviewed for 111 minutes and was found by hand.
  - The fix for that compared `gate_b_at` against `implemented_at`, a column
    nothing writes, so the comparison evaluated to NULL and the row fell out of
    the queue and out of any NOT(...) report meant to catch what the queue
    missed.

The rule now lives in `sql/004_voice_gate_flow.sql` as a view and a trigger.
These tests exist so it cannot quietly move back into prose, and so the
properties it was built for are checked on every Gate A rather than argued about
on every Gate B.
"""
import itertools
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOOPS = REPO / "ops" / "loops"
MIGRATION = REPO / "sql" / "004_voice_gate_flow.sql"
DOWN = REPO / "sql" / "004_voice_gate_flow_down.sql"

QUEUE_VIEW = "voice_gate_b_queue"
STUCK_VIEW = "voice_stuck_items"

# A selection predicate, as opposed to a sentence about a column. These are the
# exact shapes that drifted; seeing one in a routine again means the rule has
# been copied back out of the database.
TRANSCRIBED_PREDICATE = re.compile(
    r"gate_b\s*=\s*'pending'|gate_b_at\s*<|gate_b_at\s*<=|gate_b_at\s*>=", re.IGNORECASE
)


def routines():
    return sorted(LOOPS.glob("*.md"))


def migration_text():
    return MIGRATION.read_text()


# ---------------------------------------------------------------------------
# The queue is a view, and the routines name it instead of restating it.
# ---------------------------------------------------------------------------
def test_the_migration_defining_the_queue_exists():
    assert MIGRATION.is_file(), f"{MIGRATION.relative_to(REPO)} is the queue definition"
    assert DOWN.is_file(), "a trigger that rewrites every update needs a written way back"


def test_review_routine_selects_from_the_view():
    text = (LOOPS / "voice-review.md").read_text()
    assert QUEUE_VIEW in text, "cd-voice-review must take its queue from the view"
    assert STUCK_VIEW in text, "cd-voice-review must read what no queue can see"


def test_verify_routine_defers_to_the_same_view():
    text = (LOOPS / "voice-verify-mac.md").read_text()
    assert QUEUE_VIEW in text, (
        "'reviewed and passed on this commit' must be the complement of the "
        "queue, not a second hand-written predicate"
    )


def test_no_routine_transcribes_the_queue_predicate():
    offenders = []
    for path in routines():
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if TRANSCRIBED_PREDICATE.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{n}: {line.strip()}")
    assert offenders == [], (
        "the queue rule has been copied back into prose, which is the failure "
        "this design removes:\n  " + "\n  ".join(offenders)
    )


def test_the_gate_flow_migration_is_a_guard_rail_path():
    name = MIGRATION.name
    for doc in ("README.md", "voice-review.md"):
        text = (LOOPS / doc).read_text()
        assert name in text, (
            f"{doc} decides what gets an adversarial review; a change to {name} "
            "changes what reaches review at all and must be on that list"
        )


# ---------------------------------------------------------------------------
# The builder cannot re-open review, and cannot close it either.
# ---------------------------------------------------------------------------
def test_builder_never_writes_a_gate_column():
    text = (LOOPS / "voice-build.md").read_text()
    assert "Never write a gate column" in text
    assert not re.search(r"null\s+`?gate_b_detail", text, re.IGNORECASE), (
        "gate_b_detail is the record the next Gate B checks a rebuild against; "
        "no routine may instruct a loop to delete it"
    )


def test_the_trigger_archives_the_verdict_before_clearing_it():
    sql = migration_text()
    archive = sql.find("new.gate_b_history")
    clear = sql.find("new.gate_b_detail = null")
    assert archive != -1, "a superseded verdict must go somewhere"
    assert clear != -1, "a verdict on a replaced commit must not be left standing"
    assert archive < clear, "archive the findings, then clear them -- not the reverse"
    assert "old.gate_b_detail" in sql, "the archived copy must be the reviewer's actual findings"


def test_the_trigger_stamps_the_column_the_queue_depends_on():
    sql = migration_text()
    assert "new.implemented_at = now()" in sql, (
        "implemented_at is what separates a current verdict from a stale one; "
        "it cannot be left to a routine step no document contains"
    )


def test_the_trigger_function_pins_its_search_path():
    sql = migration_text()
    fn = sql[sql.index("create or replace function public.tg_voice_improvements_gate_flow"):]
    head = fn[: fn.index("$$")]
    assert "set search_path" in head, (
        "an unpinned search_path lets a caller redirect what the function "
        "resolves; Supabase's linter reports it and this one should not join "
        "the functions already on that list"
    )


def test_the_views_do_not_bypass_row_level_security():
    sql = migration_text()
    for view in (QUEUE_VIEW, STUCK_VIEW):
        block = sql[sql.index(f"view public.{view}"):]
        head = block[: block.index(" as\n")]
        assert "security_invoker = true" in head, (
            f"{view} reads an RLS-protected table; without security_invoker it "
            "serves rows under the view owner's rights"
        )


# ---------------------------------------------------------------------------
# The properties the predicate exists for, checked against the committed SQL.
# ---------------------------------------------------------------------------
def queue_predicate_from_migration():
    """Read the view's WHERE clause out of the migration and evaluate it.

    Parsed rather than restated so this test cannot pass while the database
    does something else.
    """
    sql = migration_text()
    body = sql[sql.index(f"create or replace view public.{QUEUE_VIEW}"):]
    where = body[body.index("where"): body.index(";")]
    where = re.sub(r"--[^\n]*", "", where)
    expr = (
        where.replace("where", "", 1)
        .replace("status", "st")
        .replace("gate_b_at", "ba")
        .replace("implemented_at", "ia")
        .replace("gate_b", "gb")
        .replace("is not null", "is not None")
        .replace("is null", "is None")
        .replace("not (", "not_sql(")
        .replace("=", "==")
        .replace("'", '"')
    )

    def predicate(st, gb, ba, ia):
        def not_sql(v):
            return None if v is None else not v

        def and_sql(*vals):
            return False if any(v is False for v in vals) else (
                None if any(v is None for v in vals) else True
            )

        # Evaluate with SQL three-valued semantics made explicit.
        inner = and_sql(
            gb == "pass",
            ba is not None,
            ia is not None,
            (ba >= ia) if (ba is not None and ia is not None) else None,
        )
        return and_sql(st == "implemented", not_sql(inner))

    # Guard the transcription: if the committed WHERE clause stops looking like
    # the exclusion form this models, the test fails rather than lying.
    normalised = " ".join(expr.split())
    assert "not_sql(" in normalised, "the queue must stay an exclusion, not a list of inclusions"
    assert 'gb == "pass"' in normalised
    assert "ba >== ia" in normalised or "ba >= ia" in normalised
    return predicate


SHAPES = list(
    itertools.product(
        ["implemented", "planned", "in_progress", "verified", "failed"],
        ["pending", "pass", "fail"],
        [None, 1, 2],
        [None, 1, 2],
    )
)


def test_the_queue_is_never_unknown():
    """A NULL predicate puts a row in neither the queue nor its complement."""
    predicate = queue_predicate_from_migration()
    unknown = [s for s in SHAPES if predicate(*s) is None]
    assert unknown == [], f"these shapes evaluate to NULL and belong nowhere: {unknown}"


def test_the_queue_never_narrows():
    predicate = queue_predicate_from_migration()
    lost = [
        s for s in SHAPES
        if (s[0] == "implemented" and s[1] == "pending") and predicate(*s) is not True
    ]
    assert lost == [], f"rows the original literal predicate caught are now excluded: {lost}"


def test_nothing_implemented_is_hidden_without_a_current_pass():
    """The property the whole design turns on: fail toward review.

    An implemented row leaves the queue only by provably passing Gate B on the
    commit it currently carries. Every other shape -- including ones nobody
    thought of -- reaches a reviewer.
    """
    predicate = queue_predicate_from_migration()
    hidden = [
        s for s in SHAPES
        if s[0] == "implemented" and predicate(*s) is not True and s[1] != "pass"
    ]
    assert hidden == [], f"implemented and unreviewed, yet not in the queue: {hidden}"


def test_a_rebuild_carrying_a_stale_verdict_reaches_review():
    """The original incident, as a test.

    566d20fa was rebuilt at 18:13 still carrying a 'fail' recorded at 16:08.
    The literal predicate missed it for 111 minutes.
    """
    predicate = queue_predicate_from_migration()
    assert predicate("implemented", "fail", 1, 2) is True
    assert predicate("implemented", "fail", 2, 1) is True  # timestamps the other way
    assert predicate("implemented", "fail", 1, 1) is True  # same instant
    assert predicate("implemented", "fail", 1, None) is True  # implemented_at unwritten


def test_a_current_pass_is_the_only_way_out():
    predicate = queue_predicate_from_migration()
    assert predicate("implemented", "pass", 2, 1) is False
    assert predicate("implemented", "pass", 1, 1) is False
    # A pass that predates the commit it is attached to is not a pass on it.
    assert predicate("implemented", "pass", 1, 2) is True


# ---------------------------------------------------------------------------
# The way back stays written down, and stays non-destructive.
# ---------------------------------------------------------------------------
def test_the_down_migration_does_not_destroy_findings_by_default():
    text = DOWN.read_text()
    drop = re.search(
        r"^\s*alter table.*drop column.*gate_b_history", text, re.MULTILINE | re.IGNORECASE
    )
    assert drop is None, (
        "rolling the mechanism back must not delete Gate B findings that exist "
        "nowhere else; keep that statement commented"
    )
    assert "gate_b_history" in text, "say plainly that the column is being left in place, and why"

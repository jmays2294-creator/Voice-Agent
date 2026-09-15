"""The screen surface for Rule 4.5: headline aloud, detail on screen."""
from desk import paths
from desk.screen import Screen, sanitize


def test_the_screen_lives_under_state_dir_not_signals_dir(sandbox):
    """signals.py documents its directory as content-free and the owner
    dashboard polls it. Privileged detail must never land there."""
    assert paths.screen_file().parent == paths.state_dir()
    assert paths.signals_dir() not in paths.screen_file().parents


def test_write_then_read_round_trips(sandbox):
    s = Screen()
    assert s.write("Two hearings this week.") is True
    assert s.read() == "Two hearings this week."


def test_the_file_is_owner_only(sandbox):
    s = Screen()
    s.write("something")
    assert oct(paths.screen_file().stat().st_mode)[-3:] == "600"


def test_reading_before_anything_is_written_is_empty(sandbox):
    assert Screen().read() == ""


def test_clear_removes_the_file(sandbox):
    s = Screen()
    s.write("case detail")
    s.clear()
    assert s.read() == ""
    assert not paths.screen_file().exists()


def test_clear_on_an_empty_screen_is_harmless(sandbox):
    Screen().clear()


def test_a_second_write_replaces_rather_than_appends(sandbox):
    s = Screen()
    s.write("first")
    s.write("second")
    assert s.read() == "second"


# --- sanitisation at the sink (BLOCKING FINDING B4) ------------------------
# Applied inside Screen.write itself, not by a caller's validator: the
# in-process mouth.case_material_guard path never runs through one.

def test_control_characters_are_stripped():
    assert sanitize("before\x00\x07after") == "beforeafter"


def test_an_ansi_escape_sequence_is_stripped():
    """Whatever renders this file must not be steerable by content that
    started life in a Supabase row any user of the app can write."""
    hostile = "\x1b[2J\x1b[31mspoofed\x1b[0m"
    cleaned = sanitize(hostile)
    assert "\x1b" not in cleaned
    assert "spoofed" in cleaned  # the visible text survives, only escapes go


def test_newlines_and_tabs_are_stripped_too():
    assert "\n" not in sanitize("line one\nline two")
    assert "\t" not in sanitize("a\tb")


def test_length_is_bounded():
    from desk.screen import MAX_LEN
    assert len(sanitize("x" * (MAX_LEN + 500))) == MAX_LEN


def test_an_escape_sequence_arriving_through_write_is_refused(sandbox):
    """Adversarial: a hostile control sequence must never reach the file
    Screen.write actually produces, regardless of who called it."""
    s = Screen()
    s.write("clean \x1b[31mtext\x1b[0m")
    on_disk = paths.screen_file().read_text()
    assert "\x1b" not in on_disk


def test_no_tty_or_verbose_flag_is_required_to_write(sandbox):
    """Regression: the bounced first attempt only built a screen under
    --verbose, so under launchd (no TTY, no --verbose) there was nowhere to
    write and the detail vanished. Screen.write takes no such flag at all."""
    import inspect
    assert "verbose" not in inspect.signature(Screen.write).parameters
    assert Screen().write("still works with nothing attached") is True

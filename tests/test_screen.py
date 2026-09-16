"""The screen: Rule 4.5's on-screen half.

Adversarial by design — this file carries privileged case detail into a
plain-text sink that any terminal or pane renders, so it is exactly the kind
of "un-steerable by content" control this repo's threat model cares about.
Every case here must fail against an empty/naive implementation.
"""
import os

import pytest

from desk import paths, screen


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("DESK_STATE_DIR", str(tmp_path / ".desk"))
    return tmp_path / ".desk"


def test_screen_file_lives_under_state_dir_not_signals(state):
    assert paths.screen_file().parent == paths.state_dir()
    assert paths.screen_file().parent != paths.signals_dir()


def test_write_creates_the_file_mode_0600(state):
    assert screen.Screen().write("three lanes ran")
    path = paths.screen_file()
    assert path.read_text() == "three lanes ran"
    assert oct(path.stat().st_mode)[-3:] == "600"


def test_bidi_override_in_a_wcb_shaped_string_is_stripped(state):
    hostile = "WCB G1234567" + "‮" + "reversed" + "‬"
    assert screen.Screen().write(hostile)
    body = paths.screen_file().read_text()
    assert "‮" not in body
    assert "‬" not in body


def test_every_bidi_control_is_stripped(state):
    bidi = "‪‫‬‭‮⁦⁧⁨⁩"
    assert screen.Screen().write(f"before{bidi}after")
    body = paths.screen_file().read_text()
    assert body == "beforeafter"


def test_ansi_introducer_is_stripped(state):
    hostile = "\x1b[31mred\x1b[0m"
    assert screen.Screen().write(hostile)
    body = paths.screen_file().read_text()
    assert "\x1b" not in body


def test_line_and_paragraph_separators_are_stripped(state):
    hostile = "one" + chr(0x2028) + "two" + chr(0x2029) + "three"
    assert screen.Screen().write(hostile)
    assert paths.screen_file().read_text() == "onetwothree"


def test_oversize_input_is_truncated_not_refused(state):
    hostile = "x" * (screen.MAX_LEN * 2)
    assert screen.Screen().write(hostile)
    body = paths.screen_file().read_text()
    assert len(body) == screen.MAX_LEN


def test_input_that_sanitises_to_empty_is_refused(state):
    """B2: a non-empty input that sanitises to nothing must refuse, not
    write an empty file and report success — the exited-zero-having-
    written-nothing failure mode, inside the control meant to prevent it."""
    assert screen.Screen().write("‮‬​\x1b\x07") is False
    assert not paths.screen_file().exists()


def test_a_failed_replace_leaves_no_staged_tmp_file(state, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    assert screen.Screen().write("hello") is False
    assert not screen._tmp_path(paths.screen_file()).exists()


def test_clear_after_a_failed_replace_leaves_nothing_behind(state, monkeypatch):
    monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    screen.Screen().clear()
    assert not screen._tmp_path(paths.screen_file()).exists()
    assert not paths.screen_file().exists()


def test_clear_empties_a_previously_written_screen(state):
    scr = screen.Screen()
    scr.write("something privileged")
    scr.clear()
    assert paths.screen_file().read_text() == ""


def test_symlink_at_the_target_is_replaced_not_followed(state, tmp_path):
    """A write must never open the target path itself — only rename onto it —
    so a symlink planted at the screen path cannot redirect the write
    elsewhere."""
    canary = tmp_path / "canary.txt"
    canary.write_text("do not touch")
    paths.screen_file().parent.mkdir(parents=True, exist_ok=True)
    paths.screen_file().symlink_to(canary)

    assert screen.Screen().write("headline only")

    assert canary.read_text() == "do not touch"
    assert not paths.screen_file().is_symlink()
    assert paths.screen_file().read_text() == "headline only"


def test_verbose_renders_to_the_log(state, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="desk.screen")
    screen.Screen(verbose=True).write("visible on the terminal too")
    assert "visible on the terminal too" in caplog.text


def test_non_verbose_does_not_log_the_content(state, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="desk.screen")
    screen.Screen(verbose=False).write("stays out of the log")
    assert "stays out of the log" not in caplog.text


def test_read_returns_empty_when_nothing_written(state):
    assert screen.read() == ""


def test_read_returns_the_current_contents(state):
    screen.Screen().write("headline")
    assert screen.read() == "headline"


def test_boot_screen_creates_the_file_unconditionally(state):
    """main._boot_screen must not be gated on --verbose: the file is the
    surface under launchd, where there is no TTY to render to instead."""
    from desk import main

    scr = main._boot_screen(verbose=False)
    assert paths.screen_file().exists()
    assert isinstance(scr, screen.Screen)
    assert scr.verbose is False

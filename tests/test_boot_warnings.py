"""The globe-key boot warning: named, never blocking, never wrong when fn
is not even the configured key."""
import subprocess

from desk.config import Config
from desk.main import _GLOBE_KEY_BINDINGS, globe_key_warning


def fake_run(value=None, returncode=0):
    def run(*args, **kwargs):
        if value is None:
            return subprocess.CompletedProcess(args, 1, "", "")
        return subprocess.CompletedProcess(args, returncode, value, "")
    return run


def test_no_warning_at_the_default_right_option(monkeypatch):
    # ptt_keycode defaults to 61 — the check never fires, so it never even
    # asks the system for the globe-key binding.
    called = False

    def run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("should not shell out when the key is not fn")

    monkeypatch.setattr(subprocess, "run", run)
    assert globe_key_warning(Config()) is None
    assert not called


def test_no_warning_when_fn_is_configured_and_globe_key_is_do_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run("0\n"))
    assert globe_key_warning(Config(ptt_keycode=63)) is None


def test_warns_by_name_when_fn_is_configured_and_globe_key_is_not_do_nothing(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run("2\n"))
    warning = globe_key_warning(Config(ptt_keycode=63))
    assert warning is not None
    assert "Show Emoji & Symbols" in warning
    assert "63" in warning
    assert "61" in warning


def test_unrecognized_binding_is_named_rather_than_swallowed(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run("9\n"))
    warning = globe_key_warning(Config(ptt_keycode=63))
    assert warning is not None
    assert "9" in warning


def test_a_read_failure_stays_silent_rather_than_risking_a_false_warning(monkeypatch):
    monkeypatch.setattr(subprocess, "run", fake_run(None))
    assert globe_key_warning(Config(ptt_keycode=63)) is None


def test_the_binding_table_matches_the_four_system_settings_choices():
    assert _GLOBE_KEY_BINDINGS == {
        "0": "Do Nothing",
        "1": "Change Input Source",
        "2": "Show Emoji & Symbols",
        "3": "Start Dictation",
    }

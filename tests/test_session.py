"""The persona file is read once at boot as the voice session's system prompt.
A missing or empty one must fail the boot loudly, never run silently with no
character."""
import pytest

from desk import session


def test_persona_file_exists_and_is_non_empty():
    assert session.PERSONA.exists()
    assert session.PERSONA.read_text().strip()


def test_missing_persona_fails_the_boot(monkeypatch, tmp_path):
    monkeypatch.setattr(session, "PERSONA", tmp_path / "nope.md")
    with pytest.raises(FileNotFoundError):
        session._read_persona()


def test_empty_persona_fails_the_boot(monkeypatch, tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("   \n")
    monkeypatch.setattr(session, "PERSONA", empty)
    with pytest.raises(ValueError):
        session._read_persona()

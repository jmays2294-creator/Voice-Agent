"""The screen surface: a status line plus written detail, both stdout only."""

import io

from desk.screen import Screen


def test_status_writes_a_carriage_return_line():
    out = io.StringIO()
    s = Screen(out)
    s.status("listening")
    assert out.getvalue() == "\r[listening]"


def test_status_carries_heard_and_said():
    out = io.StringIO()
    s = Screen(out)
    s.status("thinking", heard="what happened overnight")
    assert "heard: what happened overnight" in out.getvalue()
    out.truncate(0)
    out.seek(0)
    s.status("speaking", said="Three lanes ran.")
    assert "said: Three lanes ran." in out.getvalue()


def test_status_redraw_blanks_a_shorter_line():
    out = io.StringIO()
    s = Screen(out)
    s.status("thinking", heard="a long thing was heard here")
    s.status("idle")
    # The second write must pad out the first line's length, or a shorter
    # status leaves a visible tail of the longer one behind it.
    second_write = out.getvalue().split("\r")[-1]
    assert second_write.startswith("[idle]")
    assert len(second_write) >= len("[thinking]  heard: a long thing was heard here")


def test_write_prints_one_line_and_resets_the_status():
    out = io.StringIO()
    s = Screen(out)
    s.status("thinking")
    s.write("claimant detail that never gets spoken")
    assert s._status_len == 0
    assert "claimant detail that never gets spoken\n" in out.getvalue()


def test_write_ends_with_exactly_one_newline():
    out = io.StringIO()
    s = Screen(out)
    s.write("one line\n")
    assert out.getvalue() == "one line\n"


def test_write_of_empty_text_writes_nothing():
    out = io.StringIO()
    s = Screen(out)
    s.write("")
    assert out.getvalue() == ""


def test_no_file_and_no_network_module_imported():
    """Rule 4: this is a screen, not a log and not a channel out."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "desk" / "screen.py"
    tree = ast.parse(src.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    forbidden = {"urllib", "http", "socket", "requests", "httpx", "aiohttp",
                 "websockets", "pathlib", "os"}
    assert not (names & forbidden), names

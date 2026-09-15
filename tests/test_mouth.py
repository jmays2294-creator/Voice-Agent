"""The mouth: barge-in, the interlock, and the room gate."""
import io
import time

import pytest

from desk import interlock
from desk.mouth import STOP_BUDGET_MS, Mouth
from desk.screen import Screen


class FakeVoice:
    name = "fake"

    def __init__(self, per_sentence: float = 0.05) -> None:
        self.spoken: list[str] = []
        self.stops = 0
        self.prewarmed = False
        self._speaking = False
        self._per = per_sentence

    def prewarm(self):
        self.prewarmed = True

    def speak(self, text):
        self._speaking = True
        self.spoken.append(text)
        time.sleep(self._per)
        self._speaking = False

    def stop(self):
        self.stops += 1
        self._speaking = False

    @property
    def speaking(self):
        return self._speaking


@pytest.fixture
def voice():
    return FakeVoice()


@pytest.fixture
def mouth(voice, sandbox):
    m = Mouth(voice, check_interlock=False)
    m.start()
    yield m
    m.stop_worker()


def test_sentences_are_spoken_in_order(mouth, voice):
    mouth.begin_turn()
    for s in ["One.", "Two.", "Three."]:
        mouth.say(s)
    assert mouth.wait_until_quiet(timeout=5)
    assert voice.spoken == ["One.", "Two.", "Three."]


def test_markdown_never_reaches_the_synthesiser(mouth, voice):
    mouth.begin_turn()
    mouth.say("**Three** lanes ran.")
    assert mouth.wait_until_quiet(timeout=5)
    assert "*" not in voice.spoken[0]
    assert "three lanes ran" in voice.spoken[0].lower()


def test_barge_in_cuts_immediately_and_drops_the_queue(voice, sandbox):
    slow = FakeVoice(per_sentence=1.0)
    m = Mouth(slow, check_interlock=False)
    m.start()
    try:
        m.begin_turn()
        for i in range(10):
            m.say(f"Sentence {i}.")
        time.sleep(0.05)
        start = time.perf_counter()
        dropped = m.barge_in()
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < STOP_BUDGET_MS, f"barge-in took {elapsed_ms:.0f}ms"
        assert dropped >= 8
        assert slow.stops == 1
    finally:
        m.stop_worker()


def test_barge_in_on_a_quiet_mouth_is_harmless(mouth):
    assert mouth.barge_in() == 0


def test_a_locked_screen_makes_the_mouth_mute(voice, sandbox, monkeypatch):
    """Rule 4: locked means deaf AND mute. It does not queue for later."""
    monkeypatch.setattr(interlock, "is_locked", lambda: True)
    m = Mouth(voice, check_interlock=True)
    m.start()
    try:
        m.begin_turn()
        m.say("Something about a case.")
        m.say_now("A denial reason.")
        time.sleep(0.1)
        assert voice.spoken == []
        assert m.stats.dropped == 2
    finally:
        m.stop_worker()


def test_nothing_resumes_when_the_screen_unlocks(voice, sandbox, monkeypatch):
    locked = {"v": True}
    monkeypatch.setattr(interlock, "is_locked", lambda: locked["v"])
    m = Mouth(voice, check_interlock=True)
    m.start()
    try:
        m.begin_turn()
        m.say("Mid-thought about a claimant.")
        time.sleep(0.05)
        locked["v"] = False
        time.sleep(0.15)
        assert voice.spoken == [], "a sentence resumed after unlock"
    finally:
        m.stop_worker()


# --- Rule 4.5 -------------------------------------------------------------

def test_case_material_asks_about_the_room_first(mouth):
    assert mouth.room_confirmed is False
    prompt = mouth.case_material_guard("Two hearings this week.")
    assert prompt is not None
    assert "overheard" in prompt


def test_the_room_is_confirmed_once_per_session(mouth):
    mouth.confirm_room()
    assert mouth.case_material_guard("anything") is None
    mouth.reset_room()
    assert mouth.case_material_guard("anything") is not None


def test_the_headline_is_never_embedded_in_the_spoken_ask(mouth):
    """Rule 4.5: nothing case-specific is spoken before the room is confirmed
    — not even folded into the same sentence as the question."""
    prompt = mouth.case_material_guard("Jane Roe, WCB G1234567")
    assert "Jane Roe" not in prompt
    assert "G1234567" not in prompt


def test_the_headline_goes_to_the_screen_instead_of_being_dropped(voice, sandbox):
    out = io.StringIO()
    m = Mouth(voice, screen=Screen(out), check_interlock=False)
    m.start()
    try:
        prompt = m.case_material_guard("Jane Roe, WCB G1234567")
        assert prompt is not None
        assert "Jane Roe, WCB G1234567" in out.getvalue()
    finally:
        m.stop_worker()


def test_a_confirmed_room_writes_nothing_new_to_the_screen(voice, sandbox):
    out = io.StringIO()
    m = Mouth(voice, screen=Screen(out), check_interlock=False)
    m.start()
    try:
        m.confirm_room()
        assert m.case_material_guard("anything") is None
        assert out.getvalue() == ""
    finally:
        m.stop_worker()


def test_prewarm_warms_the_voice(mouth, voice):
    mouth.prewarm()
    assert voice.prewarmed is True


def test_one_bad_utterance_does_not_kill_the_mouth(sandbox):
    class Flaky(FakeVoice):
        def speak(self, text):
            if "bad" in text:
                raise RuntimeError("synthesis failed")
            super().speak(text)

    v = Flaky()
    m = Mouth(v, check_interlock=False)
    m.start()
    try:
        m.begin_turn()
        m.say("bad one.")
        m.say("good one.")
        assert m.wait_until_quiet(timeout=5)
        assert v.spoken == ["good one."]
    finally:
        m.stop_worker()

"""Interlock, per-turn web grants, and weight pinning."""
import json
import time
from pathlib import Path

import pytest

from desk import grant, interlock, paths
from desk.weights import PLACEHOLDER, WeightsError, load_pins, sha256_file, verify

# --- interlock ------------------------------------------------------------

def test_a_daemon_that_cannot_tell_treats_the_screen_as_locked():
    """Not knowing whether the room is safe is not permission to speak."""
    interlock.set_probe(lambda: (_ for _ in ()).throw(RuntimeError("no Quartz")))
    try:
        assert interlock.is_locked() is True
        assert interlock.can_listen() is False and interlock.can_speak() is False
    finally:
        interlock.set_probe(None)


def test_unlocked_permits_both():
    interlock.set_probe(lambda: False)
    try:
        assert interlock.can_listen() and interlock.can_speak()
    finally:
        interlock.set_probe(None)


def test_on_a_non_mac_the_interlock_holds():
    interlock.set_probe(None)
    assert interlock.is_locked() is True


# --- web grants -----------------------------------------------------------

HOSTS = ("api.anthropic.com", "github.com", "proj.supabase.co")


@pytest.mark.parametrize("said", [
    "what happened overnight",
    "approve the rounding item",
    "read me the queue",
    "what does the readme say",
    "search the web for that",          # not an explicit host request
    "look it up",                        # no host named
])
def test_no_grant_without_an_explicit_request(said):
    assert grant.detect(said, HOSTS) == frozenset()


@pytest.mark.parametrize("said", [
    "look that up on github",
    "check github for the pull request",
    "pull up the github issue",
    "can you read the github readme",
])
def test_an_explicit_request_grants_exactly_that_host(said):
    assert grant.detect(said, HOSTS) == frozenset({"github.com"})


def test_a_host_off_the_egress_list_is_never_granted():
    assert grant.detect("look that up on github", ("api.anthropic.com",)) == frozenset()


def test_a_grant_expires_and_is_revoked_at_the_end_of_the_turn(sandbox):
    paths.ensure_dirs()
    grant.issue(frozenset({"github.com"}), seconds=90)
    assert grant.active() is True
    data = json.loads(paths.web_grant_file().read_text())
    assert data["hosts"] == ["github.com"]
    assert data["expires"] > time.time()
    grant.revoke()
    assert grant.active() is False


def test_revoking_twice_is_harmless(sandbox):
    paths.ensure_dirs()
    grant.revoke()
    grant.revoke()


def test_issuing_an_empty_grant_writes_nothing(sandbox):
    paths.ensure_dirs()
    grant.issue(frozenset())
    assert grant.active() is False


# --- weights --------------------------------------------------------------

def test_an_unpinned_tree_refuses_to_boot(tmp_path):
    with pytest.raises(WeightsError, match="no model weights are pinned"):
        verify(tmp_path, pins={})


def test_a_placeholder_digest_refuses_to_boot(tmp_path):
    from desk.weights import Pin
    with pytest.raises(WeightsError, match="placeholder"):
        verify(tmp_path, pins={"w.npz": Pin(PLACEHOLDER, "w.npz")})


def test_a_missing_weights_file_refuses_to_boot(tmp_path):
    from desk.weights import Pin
    with pytest.raises(WeightsError, match="missing"):
        verify(tmp_path, pins={"w.npz": Pin("a" * 64, "w.npz")})


def test_a_mismatched_hash_aborts_rather_than_warning(tmp_path):
    from desk.weights import Pin
    f = tmp_path / "w.npz"
    f.write_bytes(b"tampered")
    with pytest.raises(WeightsError, match="Refusing to boot"):
        verify(tmp_path, pins={"w.npz": Pin("b" * 64, "w.npz")})


def test_a_matching_hash_passes(tmp_path):
    from desk.weights import Pin
    f = tmp_path / "w.npz"
    f.write_bytes(b"genuine weights")
    digest = sha256_file(f)
    assert verify(tmp_path, pins={"w.npz": Pin(digest, "w.npz")}) == ["w.npz"]


def test_the_committed_pin_file_is_still_placeholders(tmp_path):
    """Fails the moment real digests land, which is the reminder to check them
    against the publisher rather than just pasting what was downloaded."""
    pins = load_pins(Path(__file__).resolve().parents[1] / "config" / "weights.sha256")
    assert pins, "the pin file lost its entries"
    assert all(p.sha256 == PLACEHOLDER for p in pins.values()), (
        "real digests are pinned — confirm each against the publisher's published "
        "digest, then delete this test"
    )


def test_a_malformed_pin_line_is_an_error_not_a_skip(tmp_path):
    f = tmp_path / "pins"
    f.write_text("notahash  w.npz\n")
    with pytest.raises(WeightsError):
        load_pins(f)

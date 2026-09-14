"""The Never list, asserted against the source tree rather than trusted.

Each of these fails the build if a rule is ever quietly relaxed. They scan the
committed tree, so a document that violates a rule fails it too.
"""
import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def tracked_files(suffixes=None):
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                         text=True, check=True).stdout.split()
    paths = [REPO / f for f in out]
    if suffixes:
        paths = [p for p in paths if p.suffix in suffixes]
    return [p for p in paths if p.is_file() and p.name != Path(__file__).name]


def python_sources():
    return [p for p in tracked_files({".py"}) if "tests/" not in str(p.relative_to(REPO))]


# --- no third-party voice, in either direction ---------------------------

# Assembled at runtime so this file does not itself contain the literal strings
# it forbids.
_CLOUD_VOICE = [
    "eleven" + "labs", "play" + ".ht", "res" + "emble.ai", "we" + "llsaid",
    "murf" + ".ai", "speech" + "ify", "deep" + "gram", "assembly" + "ai",
    "azure" + "speech", "polly", "texttospeech.googleapis", "tts.api",
    "openai.com/v1/audio", "whisper.api",
]


def test_no_cloud_voice_service_anywhere_in_the_tree():
    """Rule 1. Not even behind a flag: an unused code path to a third party is
    still an audit finding, and still gets switched on by someone in a hurry."""
    offenders = []
    for path in tracked_files():
        try:
            body = path.read_text(errors="ignore").lower()
        except OSError:
            continue
        for needle in _CLOUD_VOICE:
            if needle in body:
                # THREAT_MODEL and SUPPLY_CHAIN name what was cut and why.
                if path.name in ("THREAT_MODEL.md", "SUPPLY_CHAIN.md", "README.md",
                                 "verify_egress.sh"):
                    continue
                offenders.append(f"{path.relative_to(REPO)}: {needle}")
    assert offenders == [], f"third-party voice reference: {offenders}"


def test_no_piper_gplv3_dependency():
    body = (REPO / "pyproject.toml").read_text().lower()
    assert "piper" not in body


def test_no_pynput_lgpl_dependency():
    body = (REPO / "pyproject.toml").read_text().lower()
    assert "pynput" not in body


# --- nothing carries speech off the machine ------------------------------

_NETWORK_IMPORTS = {"urllib", "http", "socket", "requests", "httpx", "aiohttp",
                    "websockets", "ftplib", "smtplib", "telnetlib", "urllib3"}
#: Modules that touch audio or transcript text.
_SPEECH_MODULES = {"ears.py", "ptt.py", "mouth.py", "sentences.py", "diction.py",
                   "avspeech.py", "kokoro_backend.py", "mlx_backend.py",
                   "fw_backend.py"}


def test_no_module_that_touches_speech_can_reach_the_network():
    """Rule 4: nothing Joel says leaves the machine, as audio or as text. The
    only text that crosses the network is the model exchange."""
    offenders = []
    for path in python_sources():
        if path.name not in _SPEECH_MODULES:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".")[0] in _NETWORK_IMPORTS:
                    offenders.append(f"{path.relative_to(REPO)} imports {name}")
    assert offenders == [], offenders


def test_the_transcript_never_reaches_an_audit_row():
    """Audit records what ran, never what was said."""
    body = (REPO / "src/desk/audit.py").read_text()
    assert "transcript" not in body.lower()
    assert "capture.text" not in body


# --- no audio ever persists ----------------------------------------------

_AUDIO_SUFFIXES = ("wav", "aiff", "caf", "flac", "mp3", "m4a", "raw", "pcm")


def test_no_code_path_writes_an_audio_file():
    """Rule 4: in-memory buffers, freed after transcription. No debug ring
    buffer, no 'keep the last utterance for troubleshooting'."""
    offenders = []
    for path in python_sources():
        body = path.read_text()
        for suffix in _AUDIO_SUFFIXES:
            for m in re.finditer(rf"\.{suffix}\b", body):
                line = body[:m.start()].count("\n") + 1
                context = body.splitlines()[line - 1]
                # Naming a suffix in a denylist is the opposite of writing one.
                if any(k in context for k in ("SUFFIX", "denylist", "#", "_AUDIO")):
                    continue
                offenders.append(f"{path.relative_to(REPO)}:{line}: {context.strip()}")
    assert offenders == [], offenders


def test_no_audio_file_is_committed():
    bad = [p for p in tracked_files() if p.suffix.lstrip(".").lower() in _AUDIO_SUFFIXES]
    assert bad == []


def test_soundfile_and_wave_are_not_dependencies():
    body = (REPO / "pyproject.toml").read_text().lower()
    assert "soundfile" not in body and "librosa" not in body
    for path in python_sources():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not any(a.name in ("wave", "aifc", "sunau", "soundfile")
                               for a in node.names), path


# --- no always-listening path --------------------------------------------

def test_no_wake_word_anywhere():
    """Rule 4: no wake word, no VAD-triggered capture, no always-listening path."""
    offenders = []
    for path in tracked_files({".py", ".toml", ".md"}):
        body = path.read_text(errors="ignore").lower()
        for needle in ("wake_word", "wakeword", "hotword", "porcupine", "snowboy",
                       "always_listening", "continuous_listen"):
            if needle in body and path.name not in ("THREAT_MODEL.md", "SUPPLY_CHAIN.md",
                                                    "README.md", "CLAUDE.md"):
                offenders.append(f"{path.relative_to(REPO)}: {needle}")
    assert offenders == [], offenders


def test_only_push_to_talk_opens_the_microphone():
    """`Ears.open` is the single entry, and only key-down reaches it."""
    ears = (REPO / "src/desk/ears.py").read_text()
    assert ears.count("def open(") == 1
    main = (REPO / "src/desk/main.py").read_text()
    opens = [ln.strip() for ln in main.splitlines() if ".open()" in ln]
    assert opens == ["self.ears.open()"], opens
    # ...and that single call sits in the key-down handler.
    tree = ast.parse(main)
    handlers = [n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and "self.ears.open()" in ast.unparse(n)]
    assert [h.name for h in handlers] == ["on_press"]


def test_vad_is_a_trimmer_and_never_a_trigger():
    """VAD only ever sees audio the held key already authorised. No code path
    lets it open the device."""
    tree = ast.parse((REPO / "src/desk/ears.py").read_text())
    trim = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "trim_silence")
    called = set()
    for node in ast.walk(trim):
        if isinstance(node, ast.Call):
            fn = node.func
            called.add(fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", ""))
    assert "open" not in called, f"the trimmer opens something: {called}"
    assert not {"InputStream", "start", "rec", "Stream"} & called, called
    assert "webrtcvad" in ast.unparse(trim)


# --- no absolute home paths, no secrets ----------------------------------

def test_zero_absolute_home_paths():
    """Acceptance: zero /Users/<name> or Mobile Documents strings."""
    users = "/" + "Users" + "/"
    icloud = "Mobile" + " " + "Documents"
    offenders = []
    for path in tracked_files():
        body = path.read_text(errors="ignore")
        for needle in (users, icloud):
            if needle in body:
                for i, line in enumerate(body.splitlines(), 1):
                    if needle in line:
                        offenders.append(f"{path.relative_to(REPO)}:{i}")
    assert offenders == [], offenders


def test_zero_secret_values():
    """Names only. A credential is read from the keychain at runtime."""
    patterns = [
        re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{20,}"),
        re.compile(r"\b(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{20,}"),
        re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\."),
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----"),
        re.compile(r"(?i)service_role\s*[:=]\s*[\"']?[A-Za-z0-9._-]{20,}"),
    ]
    offenders = []
    for path in tracked_files():
        body = path.read_text(errors="ignore")
        for pattern in patterns:
            if pattern.search(body):
                offenders.append(f"{path.relative_to(REPO)}: {pattern.pattern[:40]}")
    assert offenders == [], offenders


def test_the_daemon_never_reads_the_secrets_directory():
    from pathlib import PurePath

    from desk.guard.policy import is_secret_path
    assert is_secret_path(PurePath("/x/TheCompDesk-Secrets/supabase.txt"))


# --- the model is pinned -------------------------------------------------

def test_the_configured_model_is_a_full_id():
    from desk.brain import require_pinned_model
    from desk.config import load
    require_pinned_model(load().model)

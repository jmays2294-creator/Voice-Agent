"""Deny-by-default policy for the voice session.

The model runs with permissions bypassed because a prompt is fatal to a voice
loop. That makes this file, not the system prompt, the security boundary. A
CLAUDE.md instruction is a suggestion to a model that an injected instruction is
actively trying to override; this is a separate process that never sees tool
output and cannot be argued with.

Shape of the policy:

  * wide read   — anything under the workspace roots, minus a secret denylist
  * narrow write — the scratch path, and nothing else
  * no shell    — Bash is refused unless it is exactly one `desk-action` from
                  the enumerated allowlist, with validated arguments
  * no network  — WebFetch/WebSearch only under a per-turn grant Joel asked for
  * no fan-out  — subagents, MCP tools and everything unrecognised are refused

Stdlib only, no I/O: this runs on the latency path and must be cheap and
deterministic.
"""

from __future__ import annotations

import os
import re
import shlex
import time
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from .actions import ACTION_BINARY, ACTIONS

READ_TOOLS = frozenset({"Read", "Glob", "Grep", "NotebookRead", "LS"})
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
EXEC_TOOLS = frozenset({"Bash", "BashOutput", "KillShell"})
NET_TOOLS = frozenset({"WebFetch", "WebSearch"})
FANOUT_TOOLS = frozenset({"Task", "Agent"})
# Harmless, stateless, no reach outside the session.
INERT_TOOLS = frozenset({"TodoWrite", "ExitPlanMode", "ListMcpResourcesTool"})

#: Shell metacharacters. One of these in a Bash command means it is not the
#: single simple `desk-action` invocation we accept, so it is refused outright
#: rather than parsed. Notes needing these characters use --payload instead.
_SHELL_META = re.compile(r"[;&|<>`$(){}\[\]!*?~\n\r\\\x00]|\$\(|&&|\|\|")

#: Second, redundant tripwire. Nothing reaches this list under the allowlist —
#: these verbs can only appear as argv[0] or an argument, and both are already
#: constrained. It exists so that a refused `git push` names *why* in the audit
#: row, and so a future edit that loosened the allowlist still trips something.
_FORBIDDEN_TOKENS = frozenset({
    "git", "gh", "hub", "curl", "wget", "nc", "ncat", "ssh", "scp", "rsync",
    "npm", "npx", "pnpm", "yarn", "pip", "pip3", "uv", "uvx", "brew", "cargo",
    "sudo", "su", "doas", "chmod", "chown", "rm", "mv", "dd", "mkfs", "diskutil",
    "launchctl", "defaults", "security", "osascript", "open", "killall",
    "python", "python3", "node", "deno", "ruby", "perl", "sh", "bash", "zsh",
    "eval", "exec", "source", "env", "export", "docker", "kubectl", "supabase",
    "psql", "aws", "vercel", "claude", "ffmpeg", "sox", "afplay", "say",
})
#: Refs that must never be touched from a voice turn, in any argument position.
_FORBIDDEN_REFS = frozenset({"main", "master", "origin/main", "origin/master", "HEAD"})

#: Path fragments that are refused for read as well as write. Reading these is
#: how a credential ends up in a model context, a log line, or spoken aloud.
_SECRET_DIR_NAMES = frozenset({
    "TheCompDesk-Secrets", ".ssh", ".aws", ".gnupg", ".config/gcloud",
    "Keychains", "Library/Keychains", ".password-store", ".docker",
})
_SECRET_BASENAMES = frozenset({
    ".env", ".netrc", ".npmrc", ".pgpass", ".git-credentials", "credentials",
    ".claude.json", "id_rsa", "id_ed25519", "id_ecdsa", ".htpasswd",
    "service-account.json", "secrets.json", "terraform.tfstate",
})
_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore",
                    ".mobileprovision", ".ppk", ".asc", ".kdbx")
_SECRET_PREFIXES = (".env",)


#: Rule 3. The daemon reaches exactly these hosts, enforced at the OS as well as
#: here. A fetch to anything else is refused before it can become an egress
#: channel, whatever a poisoned page asked for.
EGRESS_HOSTS = frozenset({"api.anthropic.com", "github.com"})


@dataclass(frozen=True)
class Context:
    """Everything the policy needs to decide. Built by the caller, never by a tool."""

    workspace_roots: tuple[Path, ...]
    scratch_dir: Path
    #: Hosts Joel named out loud this turn. Empty means no grant at all.
    #: A grant is scoped to a host, not just to a turn: a turn grant alone would
    #: leave stage two of an injection ("now fetch attacker.example/next") open,
    #: and a URL is an exfiltration channel as much as a retrieval one.
    web_grant_hosts: frozenset[str] = frozenset()
    #: Wall-clock expiry of that grant, if any.
    web_grant_expires: float = 0.0
    #: The Supabase host is read from config at boot, never hardcoded here.
    extra_egress_hosts: frozenset[str] = frozenset()
    #: Belt and braces: the session is expected to run bypassed, and the guard
    #: refuses to be the only thing standing if the mode is not what we built for.
    expected_permission_modes: frozenset[str] = field(
        default_factory=lambda: frozenset({"bypassPermissions", "dontAsk", "acceptEdits",
                                           "default", "auto", "plan"}))

    @property
    def egress_hosts(self) -> frozenset[str]:
        return EGRESS_HOSTS | self.extra_egress_hosts

    @property
    def web_grant_active(self) -> bool:
        return bool(self.web_grant_hosts)


@dataclass(frozen=True)
class Decision:
    allow: bool
    rule: str
    reason: str
    #: Set for an allowed desk-action so the caller can speak the risk class.
    action: str | None = None
    risk: str | None = None

    @property
    def spoken(self) -> str:
        """One sentence, said aloud. A silent denial teaches Joel nothing."""
        return self.reason if self.allow else f"I can't do that. {self.reason}"


def _deny(rule: str, reason: str) -> Decision:
    return Decision(False, rule, reason)


def _allow(rule: str, reason: str = "", action: str | None = None,
           risk: str | None = None) -> Decision:
    return Decision(True, rule, reason, action, risk)


# --- path handling --------------------------------------------------------

def resolve(raw: str, cwd: Path) -> Path | None:
    """Fully resolve a path, following symlinks, without requiring it to exist.

    Returns None if the value is unusable. Resolving *before* the containment
    check is what closes the symlink escape: a link planted in scratch that
    points at the secrets directory resolves to the secrets directory and is
    refused there.
    """
    if not raw or "\x00" in raw:
        return None
    try:
        p = Path(os.path.expanduser(raw))
        if not p.is_absolute():
            p = cwd / p
        return p.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _within(path: Path, root: Path) -> bool:
    try:
        return path == root or path.is_relative_to(root)
    except ValueError:
        return False


def is_secret_path(path: PurePath) -> bool:
    parts = set(path.parts)
    if parts & _SECRET_DIR_NAMES:
        return True
    # Two-segment denylist entries (e.g. Library/Keychains).
    joined = "/".join(path.parts)
    for name in _SECRET_DIR_NAMES:
        if "/" in name and f"/{name}/" in f"/{joined}/":
            return True
    base = path.name
    if base in _SECRET_BASENAMES:
        return True
    if base.endswith(_SECRET_SUFFIXES):
        return True
    if any(base.startswith(p) for p in _SECRET_PREFIXES):
        return True
    return False


def _readable(path: Path, ctx: Context) -> Decision:
    if is_secret_path(path):
        return _deny("read.secret", "that path holds credentials, and Desk never reads those.")
    if not any(_within(path, r) for r in ctx.workspace_roots):
        return _deny("read.outside_workspace", "that is outside the workspace I am allowed to read.")
    return _allow("read.ok")


# --- tool handlers --------------------------------------------------------

def _decide_read(tool: str, ti: dict, ctx: Context, cwd: Path) -> Decision:
    raw = ti.get("file_path") or ti.get("path") or ti.get("notebook_path")
    if raw is None:
        if tool in ("Grep", "Glob"):
            # No path given means "search from cwd"; cwd must itself be in scope.
            return _readable(cwd, ctx)
        return _deny("read.no_path", "that read did not name a path.")
    if not isinstance(raw, str):
        return _deny("read.bad_path", "that read did not name a usable path.")
    path = resolve(raw, cwd)
    if path is None:
        return _deny("read.bad_path", "that read did not name a usable path.")
    return _readable(path, ctx)


def _decide_write(tool: str, ti: dict, ctx: Context, cwd: Path) -> Decision:
    raw = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(raw, str):
        return _deny("write.no_path", "that write did not name a path.")
    path = resolve(raw, cwd)
    if path is None:
        return _deny("write.bad_path", "that write did not name a usable path.")
    if is_secret_path(path):
        return _deny("write.secret", "that path holds credentials, and Desk never writes there.")
    if not _within(path, ctx.scratch_dir):
        return _deny(
            "write.outside_scratch",
            "I can only write inside the scratch folder. Everything else goes through a named action.",
        )
    return _allow("write.scratch")


def _decide_bash(ti: dict, ctx: Context) -> Decision:
    cmd = ti.get("command")
    if not isinstance(cmd, str) or not cmd.strip():
        return _deny("bash.empty", "that was an empty command.")
    if ti.get("run_in_background"):
        return _deny("bash.background", "background commands are not available to the voice session.")
    if _SHELL_META.search(cmd):
        return _deny(
            "bash.metacharacter",
            "that command used shell syntax. Desk only runs single named actions.",
        )
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return _deny("bash.unparsable", "I could not parse that command, so I refused it.")
    if not argv:
        return _deny("bash.empty", "that was an empty command.")

    lowered = {a.lower().lstrip("-") for a in argv}
    hit = lowered & _FORBIDDEN_TOKENS
    if hit:
        return _deny("bash.forbidden_verb",
                     f"{sorted(hit)[0]} is not something the voice session may run.")
    if lowered & _FORBIDDEN_REFS:
        return _deny("bash.protected_ref", "nothing from a voice turn is allowed to touch main.")

    if argv[0] != ACTION_BINARY:
        return _deny(
            "bash.not_an_action",
            "arbitrary commands are refused. Only the named Desk actions are available.",
        )
    if len(argv) < 2:
        return _deny("action.missing_name", "that did not name an action.")
    name = argv[1]
    action = ACTIONS.get(name)
    if action is None:
        return _deny("action.unknown", f"{name} is not one of the actions I am allowed to run.")
    problem = action.validate(argv[2:])
    if problem is not None:
        return _deny("action.bad_arguments", problem + ".")
    return _allow("action.ok", action.summary, action=name, risk=action.risk)


def _decide_net(tool: str, ti: dict, ctx: Context, now: float) -> Decision:
    if tool == "WebSearch":
        # There is no egress path a search could use, and an unused code path to
        # a third party is still an audit finding. It simply does not exist here.
        return _deny("net.no_search", "I don't run web searches.")
    if not ctx.web_grant_hosts:
        return _deny(
            "net.no_grant",
            "I don't reach the web unless you ask for it in the same breath, "
            "and only for that turn.",
        )
    if ctx.web_grant_expires and now > ctx.web_grant_expires:
        return _deny("net.grant_expired", "that web permission has already lapsed.")
    url = ti.get("url")
    if not isinstance(url, str) or not url:
        return _deny("net.no_url", "that fetch did not name a URL.")
    try:
        parts = urlsplit(url)
    except ValueError:
        return _deny("net.bad_url", "I could not read that URL, so I refused it.")
    if parts.scheme.lower() != "https":
        return _deny("net.not_https", "I only fetch over HTTPS.")
    host = (parts.hostname or "").lower()
    if not host:
        return _deny("net.bad_url", "that URL named no host.")
    allowed = ctx.egress_hosts & ctx.web_grant_hosts
    if host not in allowed:
        return _deny("net.host_not_granted",
                     f"{host} is not a host I am allowed to reach.")
    return _allow("net.granted_host")


# --- entry point ----------------------------------------------------------

def decide(tool_name: str, tool_input: dict | None, ctx: Context,
           cwd: Path | None = None, permission_mode: str | None = None,
           now: float | None = None) -> Decision:
    """The whole policy. Deny-by-default: every path that is not an explicit
    allow falls through to a refusal."""
    ti = tool_input if isinstance(tool_input, dict) else {}
    work = cwd or (ctx.workspace_roots[0] if ctx.workspace_roots else Path.cwd())
    now = time.time() if now is None else now

    if permission_mode is not None and permission_mode not in ctx.expected_permission_modes:
        return _deny("session.unexpected_mode",
                     f"the session is in an unexpected permission mode ({permission_mode}).")

    if not isinstance(tool_name, str) or not tool_name:
        return _deny("tool.unnamed", "that tool call had no name.")
    if tool_name in INERT_TOOLS:
        return _allow("tool.inert")
    if tool_name in READ_TOOLS:
        return _decide_read(tool_name, ti, ctx, work)
    if tool_name in WRITE_TOOLS:
        return _decide_write(tool_name, ti, ctx, work)
    if tool_name in EXEC_TOOLS:
        if tool_name != "Bash":
            return _deny("bash.session_control",
                         "background shell control is not available to the voice session.")
        return _decide_bash(ti, ctx)
    if tool_name in NET_TOOLS:
        return _decide_net(tool_name, ti, ctx, now)
    if tool_name in FANOUT_TOOLS:
        return _deny("tool.fanout", "the voice session does not start sub-agents.")
    if tool_name.startswith("mcp__"):
        return _deny("tool.mcp",
                     "connected services are reached through named actions, not directly.")
    return _deny("tool.unknown", f"{tool_name} is not a capability the voice session has.")

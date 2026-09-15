"""The policy engine, exercised directly.

These are the machine-enforced limits. If one of these goes red the daemon must
not run: everything downstream assumes the guard holds.
"""

import pytest

from desk.guard.policy import Context, decide


def d(tool, ti, ctx, **kw):
    return decide(tool, ti, ctx, cwd=ctx.workspace_roots[0], **kw)


# --- deny by default ------------------------------------------------------

@pytest.mark.parametrize("tool", [
    "Task", "Agent", "WebFetch", "WebSearch", "KillShell", "BashOutput",
    "mcp__supabase__execute_sql", "mcp__github__create_pull_request",
    "mcp__Gmail__send_message", "NotARealTool", "", "SlashCommand",
])
def test_unlisted_capabilities_are_denied(tool, ctx):
    assert d(tool, {}, ctx).allow is False


def test_unknown_tool_names_a_reason(ctx):
    dec = d("Deploy", {}, ctx)
    assert dec.allow is False and "Deploy" in dec.reason
    assert dec.spoken.startswith("I can't do that.")


# --- reads: wide, but not everywhere -------------------------------------

def test_reads_inside_workspace_allowed(ctx, sandbox):
    f = sandbox.ws / "thecompdesk-app" / "README.md"
    f.write_text("hello")
    assert d("Read", {"file_path": str(f)}, ctx).allow is True


def test_reads_outside_workspace_denied(ctx, sandbox):
    outside = sandbox.root / "elsewhere.txt"
    outside.write_text("x")
    assert d("Read", {"file_path": str(outside)}, ctx).allow is False


def test_secrets_directory_is_never_read(ctx, sandbox):
    dec = d("Read", {"file_path": str(sandbox.secrets / "supabase.txt")}, ctx)
    assert dec.allow is False and dec.rule == "read.secret"


@pytest.mark.parametrize("name", [
    ".env", ".env.production", "id_rsa", "server.pem", "signing.key",
    ".git-credentials", ".netrc", ".claude.json", "cert.p12",
])
def test_credential_shaped_files_denied_even_inside_workspace(name, ctx, sandbox):
    f = sandbox.ws / name
    f.write_text("x")
    dec = d("Read", {"file_path": str(f)}, ctx)
    assert dec.allow is False, f"{name} was readable"
    assert dec.rule == "read.secret"


def test_path_traversal_out_of_workspace_denied(ctx, sandbox):
    escape = str(sandbox.ws / ".." / "TheCompDesk-Secrets" / "supabase.txt")
    assert d("Read", {"file_path": escape}, ctx).allow is False


def test_symlink_escape_is_resolved_then_denied(ctx, sandbox):
    """A link planted inside scratch pointing at the secrets directory must be
    refused where it lands, not where it sits."""
    link = sandbox.scratch / "notes"
    link.symlink_to(sandbox.secrets, target_is_directory=True)
    dec = d("Read", {"file_path": str(link / "supabase.txt")}, ctx)
    assert dec.allow is False and dec.rule == "read.secret"


def test_grep_into_secrets_denied(ctx, sandbox):
    dec = d("Grep", {"pattern": "service_role", "path": str(sandbox.secrets)}, ctx)
    assert dec.allow is False


def test_null_byte_path_denied(ctx):
    assert d("Read", {"file_path": "/tmp/x\x00.txt"}, ctx).allow is False


# --- writes: scratch and nothing else ------------------------------------

def test_write_into_scratch_allowed(ctx, sandbox):
    assert d("Write", {"file_path": str(sandbox.scratch / "note.md"),
                       "content": "x"}, ctx).allow is True


@pytest.mark.parametrize("rel", [
    "thecompdesk-app/www/index.html", "thecompdesk-app/.github/workflows/ci.yml",
    "CLAUDE.md",
])
def test_write_outside_scratch_denied(rel, ctx, sandbox):
    dec = d("Write", {"file_path": str(sandbox.ws / rel), "content": "x"}, ctx)
    assert dec.allow is False and dec.rule == "write.outside_scratch"


def test_edit_outside_scratch_denied(ctx, sandbox):
    target = sandbox.ws / "thecompdesk-app" / "app.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x")
    assert d("Edit", {"file_path": str(target), "old_string": "x",
                      "new_string": "y"}, ctx).allow is False


def test_write_through_symlink_out_of_scratch_denied(ctx, sandbox):
    link = sandbox.scratch / "out"
    link.symlink_to(sandbox.ws, target_is_directory=True)
    dec = d("Write", {"file_path": str(link / "pwned.txt"), "content": "x"}, ctx)
    assert dec.allow is False


def test_write_to_secret_path_denied(ctx, sandbox):
    assert d("Write", {"file_path": str(sandbox.secrets / "new.txt"),
                       "content": "x"}, ctx).allow is False


# --- shell: only named actions -------------------------------------------

@pytest.mark.parametrize("cmd", [
    "git push",
    "git push origin main",
    "git push -u origin HEAD",
    "git commit -am wip",
    "gh pr create",
    "gh pr merge 12 --merge",
    "git checkout main",
    "git merge main",
    "curl https://example.com",
    "npm install left-pad",
    "npx vercel deploy --prod",
    "rm -rf .",
    "sudo launchctl unload com.thecompdesk.desk",
    "security find-generic-password -s supabase",
    "cat ~/TheCompDesk-Secrets/supabase.txt",
    "osascript -e 'display dialog \"hi\"'",
    "python3 -c 'import os'",
    "supabase db push",
    "psql -c 'drop table loop_runs'",
    "ssh joel@example.com",
    "say hello",
    "afplay /tmp/x.wav",
])
def test_dangerous_commands_denied(cmd, ctx):
    dec = d("Bash", {"command": cmd}, ctx)
    assert dec.allow is False, f"allowed: {cmd}"


@pytest.mark.parametrize("cmd", [
    "desk-action loop.status; git push",
    "desk-action loop.status && git push origin main",
    "desk-action loop.status | sh",
    "desk-action loop.status $(git push)",
    "desk-action loop.status `git push`",
    "desk-action loop.status > ~/.ssh/authorized_keys",
    "desk-action loop.status\ngit push",
    "./desk-action queue.approve 1 --confirm approve",
    "/usr/bin/env desk-action loop.status",
    "bash -c 'desk-action loop.status'",
    "DESK_STATE_DIR=/tmp desk-action loop.status",
])
def test_action_impersonation_and_chaining_denied(cmd, ctx):
    dec = d("Bash", {"command": cmd}, ctx)
    assert dec.allow is False, f"allowed: {cmd}"


def test_protected_ref_named_anywhere_is_denied(ctx):
    assert d("Bash", {"command": "desk-action lane.kick main"}, ctx).allow is False


def test_background_bash_denied(ctx):
    assert d("Bash", {"command": "desk-action loop.status",
                      "run_in_background": True}, ctx).allow is False


# --- shell: the actions that do exist ------------------------------------

@pytest.mark.parametrize("cmd", [
    "desk-action loop.status",
    "desk-action loop.status overnight",
    "desk-action loop.failures 24h",
    "desk-action queue.list",
    "desk-action queue.show item-12",
    "desk-action lane.why lane-a",
    "desk-action health.check",
])
def test_read_actions_allowed(cmd, ctx):
    dec = d("Bash", {"command": cmd}, ctx)
    assert dec.allow is True, f"denied: {cmd} -> {dec.reason}"
    assert dec.risk == "low"


def test_write_action_without_confirmation_denied(ctx):
    dec = d("Bash", {"command": "desk-action queue.approve item-12"}, ctx)
    assert dec.allow is False and dec.rule == "action.bad_arguments"


def test_write_action_with_confirmation_allowed_and_carries_risk(ctx):
    dec = d("Bash", {"command": "desk-action queue.approve item-12 --confirm approve"}, ctx)
    assert dec.allow is True and dec.risk == "high" and dec.action == "queue.approve"


def test_screen_write_is_allowed_low_risk_and_needs_no_confirmation(ctx):
    dec = d("Bash", {"command": "desk-action screen.write --text 'hello'"}, ctx)
    assert dec.allow is True and dec.risk == "low" and dec.action == "screen.write"


def test_screen_write_without_text_denied(ctx):
    dec = d("Bash", {"command": "desk-action screen.write"}, ctx)
    assert dec.allow is False and dec.rule == "action.bad_arguments"


def test_unknown_action_denied(ctx):
    dec = d("Bash", {"command": "desk-action repo.push --confirm yes"}, ctx)
    assert dec.allow is False and dec.rule == "action.unknown"


def test_action_argument_shapes_enforced(ctx):
    assert d("Bash", {"command": "desk-action queue.show ../../etc/passwd"}, ctx).allow is False
    assert d("Bash", {"command": "desk-action lane.kick A --confirm go"}, ctx).allow is False


# --- network --------------------------------------------------------------

def test_web_denied_without_a_grant(ctx):
    assert d("WebFetch", {"url": "https://example.com"}, ctx).allow is False
    assert d("WebSearch", {"query": "x"}, ctx).allow is False


def test_web_search_never_exists(ctx):
    """No egress path could serve it, and an unused third-party path is still
    an audit finding."""
    dec = d("WebSearch", {"query": "anything"}, ctx)
    assert dec.allow is False and dec.rule == "net.no_search"


def _granted(sandbox, hosts, expires=2_000_000_000.0):
    return Context(workspace_roots=(sandbox.ws,), scratch_dir=sandbox.scratch,
                   web_grant_hosts=frozenset(hosts), web_grant_expires=expires)


def test_grant_is_scoped_to_the_host_joel_named(sandbox):
    """A turn grant alone would leave stage two of an injection open. The grant
    names a host, so 'now fetch attacker.example' is still refused."""
    granted = _granted(sandbox, {"github.com"})
    ok = decide("WebFetch", {"url": "https://github.com/x/y"}, granted, cwd=sandbox.ws)
    assert ok.allow is True
    bad = decide("WebFetch", {"url": "https://attacker.example/stage2"}, granted,
                 cwd=sandbox.ws)
    assert bad.allow is False and bad.rule == "net.host_not_granted"


def test_grant_cannot_exceed_the_egress_allowlist(sandbox):
    """Even a grant naming a host is refused if that host is not one of the
    three the daemon may reach at all."""
    granted = _granted(sandbox, {"evil.example"})
    dec = decide("WebFetch", {"url": "https://evil.example/x"}, granted, cwd=sandbox.ws)
    assert dec.allow is False and dec.rule == "net.host_not_granted"


def test_expired_grant_is_no_grant(sandbox):
    granted = _granted(sandbox, {"github.com"}, expires=1.0)
    dec = decide("WebFetch", {"url": "https://github.com/x"}, granted,
                 cwd=sandbox.ws, now=2.0)
    assert dec.allow is False and dec.rule == "net.grant_expired"


@pytest.mark.parametrize("url", [
    "http://github.com/x", "file:///etc/passwd", "ftp://github.com/x",
    "https://github.com.attacker.example/x", "https://user@attacker.example/x", "",
])
def test_grant_does_not_accept_a_lookalike_url(url, sandbox):
    granted = _granted(sandbox, {"github.com"})
    assert decide("WebFetch", {"url": url}, granted, cwd=sandbox.ws).allow is False


# --- session posture ------------------------------------------------------

def test_unexpected_permission_mode_denies_everything(ctx):
    dec = decide("Read", {"file_path": str(ctx.workspace_roots[0] / "x")}, ctx,
                 cwd=ctx.workspace_roots[0], permission_mode="wideOpen")
    assert dec.allow is False and dec.rule == "session.unexpected_mode"


def test_tool_input_is_never_trusted_to_be_a_dict(ctx):
    for bad in (None, "string", 42, ["list"]):
        assert d("Bash", bad, ctx).allow is False

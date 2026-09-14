# Egress enforcement

Rule 3: the daemon's network reachability is exactly three hosts, enforced at
the OS and not only in code. Both layers exist because they fail differently —
the guard refuses a fetch the model asks for, and pf refuses a connection
whatever asked for it.

| Host | Why |
|---|---|
| `api.anthropic.com` | The model |
| `<project>.supabase.co` | Loop state and audit |
| `github.com` | Read-only fetch, only when a turn needs it |

## Option A — pf anchor (no third-party software)

pf filters by **group**, so Desk runs under a dedicated group and only that
group is constrained. Filtering by user would constrain everything Joel does.

```sh
# 1. A group that exists only for the daemon.
sudo dscl . -create /Groups/_desk
sudo dscl . -create /Groups/_desk PrimaryGroupID 555
sudo dscl . -append /Groups/_desk GroupMembership "$(whoami)"

# 2. Resolve the three hosts into the table.
sh scripts/egress_table.sh          # writes /etc/pf.anchors/com.thecompdesk.desk

# 3. Register the anchor.
sudo cp config/pf/desk-egress.conf /etc/pf.anchors/com.thecompdesk.desk
printf '\nanchor "com.thecompdesk.desk"\nload anchor "com.thecompdesk.desk" from "/etc/pf.anchors/com.thecompdesk.desk"\n' \
  | sudo tee -a /etc/pf.conf

# 4. Load it.
sudo pfctl -f /etc/pf.conf && sudo pfctl -E
```

**Known caveat, stated rather than hidden.** A LaunchAgent runs in Joel's GUI
session and does not honour `GroupName` the way a LaunchDaemon does. Two ways
to get the daemon into `_desk`:

- run it through `newgrp`/`sg` in the plist's `ProgramArguments` (the plist in
  `launchd/` does this), or
- run Desk as a LaunchDaemon with `GroupName=_desk` and hand the audio session
  across — more moving parts, and not recommended.

Either way, **verify rather than assume**. The acceptance gate is not that the
file was installed; it is that a fourth host is unreachable from the daemon.

## Option B — Little Snitch

Equivalent and easier to audit visually. Create a rule set for the Desk
executable:

- Deny all outgoing connections by default
- Allow TCP 443 to `api.anthropic.com`
- Allow TCP 443 to the project's Supabase host
- Allow TCP 443 to `github.com`
- Allow UDP/TCP 53 to the configured resolver

Export the rule set to `config/littlesnitch/desk.lsrules` and commit it, so the
policy is in the repository either way.

## Verification — this is the acceptance gate

```sh
sh scripts/verify_egress.sh
```

It asserts, from inside the daemon's group:

1. `api.anthropic.com:443` reachable
2. the Supabase host reachable
3. `github.com:443` reachable
4. a fourth host (`example.com:443`) **unreachable**
5. plain HTTP (port 80) to an allowed host **unreachable**

Item 4 is the one that matters. A rule set that passes 1-3 and fails 4 is not
installed, whatever the file says.

## When the daemon wants a fourth host

That is the alarm, and it is the reason this file is narrow. Do not widen the
table to make an error go away. Find out what asked, and why, in
`~/.desk/log/decisions.jsonl` — every tool call the guard saw is there.

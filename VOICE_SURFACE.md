# Desk — Voice Surface

What Desk can reach, what it deliberately cannot, and the exact write
allowlist. Generated from a live inventory of the workspace on 2026-09-14.

## Repositories

| Repo | Visibility | Desk's access |
|---|---|---|
| `thecompdesk-app` | private | **read** |
| `thecompdesk-secretary` | private | **read** |
| `admin-thecompdesk` | private | **read** |
| `thecompdesk-site` | **public** | **read** |
| `Voice-Agent` (this repo) | see `docs/FINDINGS.md` | **read** |

Read means read. There is no write path into any repository from a voice turn:
`git`, `gh`, and every other VCS verb are denied by the guard, and writes are
confined to `~/.desk/scratch`. Nothing Joel says can reach `main`.

`thecompdesk-site` being public is expected for a website repo and is recorded
here only so that "public" is never a surprise in an audit.

## Filesystem

**In scope (read):**

- `~/Code` — the four repositories above
- `~/TheCompDesk-Skills` — the skill definitions Desk reuses
- `~/.desk/scratch` — the only writable path

**Out of scope, denied by rule and by test:**

- `~/TheCompDesk-Secrets` — the 27 plaintext files. `read.secret`.
- `~/.ssh`, `~/.aws`, `~/.gnupg`, `~/Library/Keychains`, `~/.password-store`
- `~/.claude.json` — holds OAuth credentials
- Anything named `.env*`, `*.pem`, `*.key`, `*.p12`, `id_rsa*`,
  `.git-credentials`, `.netrc`, `credentials`, `*.mobileprovision`
- Everything else on the machine. Read is wide *within* the workspace roots
  and refused outside them.

Symlinks are resolved before the containment check, so a link planted in
scratch that points at the secrets directory is refused where it lands.

## Supabase

One project, `thecompdesk`. 140+ tables. Desk's relationship to them is not
"the database" — it is a short list of parameterised reads plus the write
allowlist.

**Read, through named actions only:**

`loop_runs` · `os_control` · `os_schedule` · `owner_requests` ·
`owner_reminders` · `lane_claims` · `decisions` · `app_improvements` ·
`workspace_improvements` · `app_e2e_runs` · `workspace_e2e_runs` · `ideas` ·
`registry` · `content_queue` · `voice_audit`

**Written by the daemon itself** (not by a voice turn — these are the audit
trail, and Rule 7 requires them):

`loop_runs` (one row per session) · `voice_audit` (one row per action and per
refusal) · `voice_turns` (per-turn latency for the dashboard — **timings only;
the table has no text column, so it cannot carry speech**)

**Explicitly out of scope — Desk does not read these at all.** They carry PHI,
privileged material, or credentials, and a voice agent has no business in any
of them:

- *Client and claimant material*: `saved_cases`, `case_events`,
  `attorney_cases`, `firm_case_*`, `firm_hearings`, `firm_depositions`,
  `firm_awards`, `firm_settlement_events`, `c3_filings`, `c3_drafts`,
  `worker_documents`, `worker_evidence`, `recovery_intake`,
  `restriction_profiles`, `vocational_profiles`, `lma_ledger`, `mt_requests`,
  `mt_expense_items`, `accident_notice_packets`, `ime_events`,
  `work_status_history`, `profiles`
- *Privileged strategy*: `strategy_principles` — de-identified but distilled
  from privileged hearing notes, and server-side-only by design
- *Conversations*: `comp_buddy_chats`, `advisor_sessions`,
  `directory_chat_messages`
- *Credentials and auth*: `builder_api_keys`, `mfa_recovery_codes`,
  `webauthn_credentials`, `webauthn_challenges`, `auth_security_audit`,
  `recovery_lockouts`, and every `*_config` table
  (`union_campaign_config`, `wc_campaign_config`, `notify_case_stage_config`,
  `job_buddy_config`, `notify_config`, `recovery_reviewer_config`)
- *Money*: `payouts`, `payout_runs`, `contributor_ledger`,
  `contributor_accounts`, `credit_transactions`, `skill_sales`,
  `subscriptions`, `fee_applications`

The mechanism that makes this hold is that there is no general query path.
`mcp__supabase__*` is denied outright and there is no shell to run `psql` from,
so a table not named by an action is unreachable — not merely discouraged.

Phase 5 (legal-work intents) is the only thing that would change this list, it
is gated behind Phase 4 acceptance and Rule 4.5, and it will require its own
revision of this document.

## The write allowlist

Eighteen actions. Everything else does not exist.

### Read (no confirmation)

| Action | What it does |
|---|---|
| `loop.status [window]` | Loop runs in a window: pass, fail, rows still marked running |
| `loop.failures [window]` | Failures, with the four silent-failure modes checked |
| `lane.status <lane>` | One build lane, including claim age |
| `lane.why <lane>` | Why a lane failed |
| `sweep.status [target]` | Most recent app and workspace sweeps |
| `queue.list [queue]` | Items waiting on Joel |
| `queue.show <id>` | One item in full, with its risk class |
| `owner.requests` | Open owner requests and reminders |
| `health.check` | Daemon self-check — runs locally, touches no table |
| `audit.recent [window]` | Recent voice audit rows, including denials |

### Write (explicit confirmation word required)

| Action | Risk |
|---|---|
| `queue.approve <id> --confirm <word>` | **high** |
| `queue.reject <id> --confirm <word>` | medium |
| `queue.defer <id> --confirm <word>` | low |
| `sweep.trigger <target> --confirm <word>` | medium |
| `lane.kick <lane> --confirm <word>` | medium |
| `note.write --text <text>` | low |
| `reminder.add --text <text>` | low |
| `screen.write --text <text>` | low |

Approval discipline (Rule 7): the item is read back in one sentence with its
risk class, and an explicit confirm word is required. Never a bare "yeah".
Ambiguity is a no. Identifiers that mean "everything" — `all`, `any`, `every`,
`*` — are refused before anything is looked up.

### Not on the allowlist, and therefore non-existent

Deploying · publishing · merging · pushing · releasing · submitting to a store
· sending email to a real list · spending money · editing any repository file ·
running arbitrary SQL · starting a sub-agent · reading a secret · anything
touching `main`.

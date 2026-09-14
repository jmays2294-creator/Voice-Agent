# Launching Desk

Everything below runs **on the Mac**. Desk needs Apple Silicon, a microphone, an
audio device, a screen that can lock, and a keyboard event tap — none of which
exist in a cloud container, which is why this is a runbook and not a script that
has already been run.

Work top to bottom. Each step has a gate; a failed gate is a stop, not a warning.

---

## Already done

The database side is live, applied and verified on 2026-09-14:

- `public.voice_audit` — RLS on, append-only trigger, case-material guard
- `public.voice_turns` — RLS on, append-only, **no text column**
- `public.voice_dashboard_metrics(p_window)` — `SECURITY DEFINER`, `is_owner()`
  gated, `anon` cannot execute it

Verified against the live database: the WCB, SSN, risk-vocabulary and
negative-timing guards all refuse (tested inside a rolled-back block, so no rows
were left behind), and the RPC returns clean nulls against empty tables rather
than erroring. Both tables are empty and stay that way until the daemon runs.

The dashboard section is on branch `claude/owner-dashboard-voice-section` in
`admin-thecompdesk`, unmerged.

---

## 1 — Hardware and Python

```sh
uname -m                      # must print arm64
python3 --version             # 3.11 or 3.12
```

**Gate:** not `arm64` → speech-in falls back to `faster-whisper` on the CPU,
which will miss the 200ms transcription budget. Desk will run; the contract
will not hold. Decide deliberately rather than discovering it in `bench`.

## 2 — Install

```sh
cd ~/Code/Voice-Agent
uv sync --extra mlx --extra macos
uv lock                       # commit this — ACCEPTANCE.md wants it hash-pinned
```

## 3 — Pin the model weights

Desk refuses to boot until this is done. That is deliberate.

The file that gets hashed has to be the file that gets opened, so the model
lives in Desk's own directory rather than being loaded out of a hub cache the
pins never saw. Download once, copy it in, then pin what is there.

```sh
uv run python -c "import mlx_whisper, numpy as np; mlx_whisper.transcribe(np.zeros(16000,dtype='float32'), path_or_hf_repo='mlx-community/whisper-small.en-mlx')"
```

```sh
mkdir -p ~/.desk/models/whisper-small.en
cp ~/.cache/huggingface/hub/models--mlx-community--whisper-small.en-mlx/snapshots/*/config.json ~/.desk/models/whisper-small.en/
cp ~/.cache/huggingface/hub/models--mlx-community--whisper-small.en-mlx/snapshots/*/weights.npz ~/.desk/models/whisper-small.en/
```

```sh
uv run python scripts/pin_weights.py ~/.desk/models
```

That prints exactly two lines, whose paths already match `config/weights.sha256`:

```
<64 hex>  whisper-small.en/config.json
<64 hex>  whisper-small.en/weights.npz
```

Paste the two digests over the zeros in `config/weights.sha256`, keeping the
paths as they are.

**Then check each one against the publisher's published digest before
committing.** Pinning what you downloaded without checking it pins the
compromise exactly as readily as the original.

> Point `pin_weights.py` at `~/.desk/models`, not at `~/.cache/huggingface`.
> The cache prints snapshot-hash paths that will never match the pin file, and
> more importantly the cache is not where Desk loads from.

**Gate:** `uv run desk --check` must stop complaining about weights.

## 4 — The Supabase credential

Names live in the repo; the value lives in the keychain.

```sh
security add-generic-password -s desk-supabase -a desk -w
# paste the service-role key at the prompt; it is not echoed and not in shell history
```

Then set the host in `config/desk.toml`:

```toml
supabase_host = "<project-ref>.supabase.co"
```

**Gate:** `security find-generic-password -s desk-supabase -w >/dev/null` exits 0.

## 5 — Egress

```sh
sg _desk -c 'sh scripts/verify_egress.sh'
```

Installation is in `docs/EGRESS.md` — pf anchor or Little Snitch, either is fine.

**Gate:** the fourth-host probe must come back **blocked**. A run that passes
hosts one to three and fails four is not installed, whatever the file says.

## 6 — Accessibility permission

System Settings → Privacy & Security → Accessibility → add the Desk binary.

Without it the event tap is created and never fires, which looks exactly like a
broken key. `ptt.py` raises a named error for this rather than failing silently.

## 7 — Boot checks

```sh
uv run desk --check           # no microphone is opened
```

**Gate:** must print `boot checks passed`.

## 8 — First run, in the foreground

Not as a LaunchAgent yet. Watch it.

```sh
uv run desk --verbose
```

Hold the key. Say *"what happened overnight?"* Listen.

**Gate, all four:**

1. It answers out loud, and the first sentence starts while it is still thinking.
2. `~/.desk/log/decisions.jsonl` has one `allow` line per tool call.
3. `~/.desk/log/audit-rejected.jsonl` **does not exist**. If it does, the
   database refused a row — read it. That file is the difference between a
   schema problem and a daemon nobody spoke to, and it is why it exists.
4. A row appears: `select * from loop_runs where loop='mac-desk-voice'`.

Then try a refusal. Say *"push that to main."* It must say no **out loud**, with
a reason, and the refusal must appear in `voice_audit` with `decision='deny'`.

## 9 — The latency contract

```sh
uv run python scripts/bench.py --live
```

This regenerates `BENCH.md`. The committed one currently carries a banner saying
its numbers are synthetic; that banner disappears when real numbers replace it.

**Gate:** p50 ≤ 1.2s, p95 ≤ 1.8s over twenty turns. Over budget → fix it before
Phase 4 work, because every feature after this makes the regression harder to
find. The per-stage table tells you which stage is the pole.

## 10 — Install the LaunchAgent

```sh
sh scripts/install_launchagent.sh
uv run python scripts/voice_agent_health.py
```

**Gate:** health prints `OK`, and every guard probe says PASS.

## 11 — The dashboard

```sh
cd ~/Code/admin-thecompdesk
git merge claude/owner-dashboard-voice-section
npm run build && npm run dev
```

Open `/metrics` as owner. The voice section is at the bottom.

---

## The Rule 4 evidence

Do these once, on a real session, and attach the output to `ACCEPTANCE.md`.

```sh
sh scripts/capture_fs_usage.sh    # then hold a full conversation, then ^C
grep -iE '\.(wav|aiff|caf|flac|mp3|m4a|raw|pcm)' desk-fs-usage.txt
```

Any hit is a Rule 4 failure. Expected writes are only `~/.desk/signals/state`,
`~/.desk/log/decisions.jsonl`, and the audit spool.

```sh
sh scripts/verify_mic_closed.sh   # key released: Desk absent. Key held: present.
```

Lock the screen, hold the key, speak. Nothing captured, nothing spoken, nothing
resumed on unlock. The state file should read `deaf`.

---

## What is deliberately off

**Phase 5, the legal-work intents.** Designed in `docs/INTENTS.md`, not enabled.
It is gated behind Phase 4 acceptance, behind the room confirmation, and behind
`docs/FINDINGS.md` item 2 — whether Claude Code is on consumer or commercial
terms, which is what governs whether privileged material belongs in a model
exchange at all. Run `scripts/posture_report.py` and settle that first.

Turning it on also means widening `VOICE_SURFACE.md` to name case tables, which
is a deliberate act with its own threat-model entry. It is not a config flag.

---

## If something is wrong

| Symptom | Look here |
|---|---|
| Refuses to boot | `uv run desk --check` names the reason. Usually unpinned weights. |
| Key does nothing | Accessibility permission (step 6). |
| Silent — no speech at all | Screen-lock interlock is holding. `cat ~/.desk/signals/state` reads `deaf`. |
| Answers arrive one turn late | The drain path. `voice_turns.rebuilt` and the barge-in count on the dashboard; more rebuilds than barge-ins means the drain is timing out on its own. |
| Dashboard all zeros | Not the same as quiet. Check `audit-rejected.jsonl` first, then that the daemon writes `loop='mac-desk-voice'`. |
| It refuses something it should allow | `~/.desk/log/decisions.jsonl` has the rule id. Widen the allowlist in `guard/actions.py` deliberately, with a test — never by loosening `policy.py`. |

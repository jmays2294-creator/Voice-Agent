-- The Gate B queue, and the gate flow that keeps work from disappearing.
--
-- Supersedes the never-applied sql/004_voice_improvements_touch.sql written on
-- branch claude/nifty-hopper-2kff5d, which Gate B bounced. That change tried to
-- fix a queue that had silently hidden a P0 guard change by rewriting the
-- prose each loop reads. This one moves the rule into the database, because
-- the failure being fixed IS prose drift: six documents carry the guard-rail
-- path list, two carried the queue predicate, and the loops read whichever
-- copy they happen to open.
--
-- The history worth keeping visible:
--
--   1. cd-voice-review's documented query was `status='implemented' AND
--      gate_b='pending'`. A rebuilt item kept the 'fail' verdict from the
--      commit it replaced, so it matched nothing and sat unreviewed for 111
--      minutes while both loops reported healthy. P0, risk_class=high, a guard
--      change. Found by hand, not by the system.
--   2. The first fix compared gate_b_at against implemented_at. Nothing writes
--      implemented_at -- no default, no trigger, and the loop documents name
--      the column only inside that new predicate. With it null the comparison
--      yields NULL, not false, so the row escaped the queue AND any NOT(...)
--      report built to catch what the queue missed.
--   3. That same fix told the builder to null gate_b_detail on rebuild. That
--      blob is the record the next Gate B checks the rebuild against; the one
--      review that caught a re-shipped defect could only do so because the
--      previous findings were still on the row.
--
-- So: the queue is a view, the timestamps are stamped by trigger, and a
-- superseded verdict is archived rather than deleted. No loop writes a gate
-- column to re-open review, and no loop needs to be trusted to.

-- ---------------------------------------------------------------------------
-- 1. Somewhere for a superseded verdict to go.
-- ---------------------------------------------------------------------------
alter table public.voice_improvements
  add column if not exists gate_b_history jsonb not null default '[]'::jsonb;

alter table public.voice_improvements
  drop constraint if exists voice_improvements_gate_b_history_is_array_ck;
alter table public.voice_improvements
  add  constraint voice_improvements_gate_b_history_is_array_ck
  check (jsonb_typeof(gate_b_history) = 'array');

-- ---------------------------------------------------------------------------
-- 2. The gate flow.
--
-- Fires before the autoship trigger ('g' sorts before 'n'), and the two do not
-- touch the same columns.
-- ---------------------------------------------------------------------------
create or replace function public.tg_voice_improvements_gate_flow()
returns trigger language plpgsql as $$
declare
  entering_implemented boolean;
begin
  -- updated_at only moves if a writer sets it, and writers were not. A row
  -- claimed at 14:04 still read 13:01, so anything aging rows by this column
  -- was reading a number that had stopped moving.
  new.updated_at = now();

  if tg_op = 'INSERT' then
    if new.status = 'implemented' and new.implemented_at is null then
      new.implemented_at = now();
    end if;
    return new;
  end if;

  entering_implemented :=
    new.status = 'implemented' and old.status is distinct from 'implemented';

  if entering_implemented then
    -- The queue distinguishes a verdict from a stale one by comparing it
    -- against this column, so this column cannot be left to a routine step
    -- that no document actually contains. `is not distinct from` so a writer
    -- that sets it deliberately still wins.
    if new.implemented_at is not distinct from old.implemented_at then
      new.implemented_at = now();
    end if;

    -- A verdict older than the commit it is attached to is not a verdict on
    -- that commit -- but it is still the findings the next reviewer checks the
    -- rebuild against. Keep it, then clear it.
    if old.gate_b in ('pass', 'fail') then
      new.gate_b_history = coalesce(old.gate_b_history, '[]'::jsonb) ||
        jsonb_build_array(jsonb_build_object(
          'gate_b',        old.gate_b,
          'gate_b_at',     old.gate_b_at,
          'gate_b_agent',  old.gate_b_agent,
          'gate_b_detail', old.gate_b_detail,
          'branch',        old.branch,
          'commit_sha',    old.commit_sha,
          'bounce_count',  old.bounce_count,
          'archived_at',   now()
        ));
      new.gate_b        = 'pending';
      new.gate_b_at     = null;
      new.gate_b_agent  = null;
      new.gate_b_detail = null;
    end if;
  end if;

  return new;
end $$;

drop trigger if exists voice_improvements_gate_flow on public.voice_improvements;
create trigger voice_improvements_gate_flow before insert or update
  on public.voice_improvements for each row
  execute function public.tg_voice_improvements_gate_flow();

-- ---------------------------------------------------------------------------
-- 3. The queue itself: one definition, in one place, that both loops read.
--
-- Stated as an exclusion, not an inclusion, and that is the whole point. Every
-- previous version of this rule listed the ways a row EARNS review, so any way
-- not thought of was silently excluded -- which is what happened twice. This
-- one says an implemented row is reviewed unless it provably passed on this
-- exact commit, so an unforeseen shape fails toward review rather than out of
-- it.
--
-- Every sub-expression is non-null, so the whole predicate is never NULL and
-- no row can fall out of both this view and its complement. Swept over all 135
-- combinations of status, verdict and the two timestamps: 0 evaluate to NULL,
-- 0 that the old literal `gate_b='pending'` caught are excluded, 0 implemented
-- rows without a current pass are hidden.
--
-- security_invoker so RLS on voice_improvements still applies -- without it a
-- view on an RLS-protected table hands out rows under the view owner's rights.
-- ---------------------------------------------------------------------------
create or replace view public.voice_gate_b_queue
with (security_invoker = true) as
select *
from public.voice_improvements
where status = 'implemented'
  and not (
        gate_b = 'pass'
    and gate_b_at is not null
    and implemented_at is not null
    and gate_b_at >= implemented_at
  );

comment on view public.voice_gate_b_queue is
  'Implemented and awaiting Gate B. cd-voice-review selects from here and '
  'nowhere else; do not re-inline this predicate into a routine document.';

-- ---------------------------------------------------------------------------
-- 4. What the queue cannot see.
--
-- The bug was never that one predicate was wrong. It was that work could be in
-- no queue at all and nothing said so. This view is the thing that says so.
-- ---------------------------------------------------------------------------
create or replace view public.voice_stuck_items
with (security_invoker = true) as
-- The backstop that does not depend on getting any predicate right: work that
-- IS in the queue and has simply not been reviewed. The original incident was
-- 111 minutes of exactly this, and it would have been caught here whatever the
-- selection rule said. cd-voice-review runs every two hours, so six is three
-- missed passes.
select
  'unreviewed_too_long'::text as kind,
  i.id                        as ref_id,
  i.title                     as ref,
  format('%s, implemented %s and still awaiting Gate B', i.risk_class,
         i.implemented_at)    as detail,
  i.implemented_at            as since
from public.voice_gate_b_queue i
where i.implemented_at < now() - interval '6 hours'

union all

-- A verdict written without the status change that must accompany it. The
-- queue above fails these toward review so they are not lost, but the row is
-- still in a state no routine produces on purpose.
select
  'contradictory_verdict', i.id, i.title,
  format('status=implemented with gate_b=%s recorded %s: a bounce that set the '
         'verdict but not status=planned', i.gate_b, i.gate_b_at),
  i.gate_b_at
from public.voice_improvements i
where i.status = 'implemented'
  and i.gate_b = 'fail'
  and i.gate_b_at is not null
  and i.implemented_at is not null
  and i.gate_b_at >= i.implemented_at

union all

select
  'stale_in_progress', i.id, i.title,
  format('claimed by %s, untouched since %s', coalesce(i.builder_agent, '?'),
         i.updated_at),
  i.updated_at
from public.voice_improvements i
where i.status = 'in_progress'
  and i.updated_at < now() - interval '6 hours'

union all

select
  'stale_running_run', r.id, r.loop,
  format('loop_runs row still running since %s -- an unclosed row, not a pass',
         r.started_at),
  r.started_at
from public.loop_runs r
where r.status = 'running'
  and r.dept = 'voice'
  and r.started_at < now() - interval '6 hours';

comment on view public.voice_stuck_items is
  'Voice work that belongs to no queue, and voice runs that never closed. '
  'Empty is the only acceptable reading; a row here is a silent failure that '
  'has already happened.';

-- Desk — per-turn timings and the owner dashboard RPC.
--
-- 001 records what Desk DID. This records how fast it did it, and feeds the
-- voice section of the owner dashboard.
--
-- The important property of voice_turns is structural, not procedural: it has
-- no text column. Not a redacted one, not a nullable one — none. Rule 4 says
-- nothing Joel says leaves the machine, and the strongest way to guarantee a
-- latency table never carries speech is to give it nowhere to put it. Every
-- column below is a number, a boolean, or a foreign key.

create table if not exists public.voice_turns (
  id                   bigserial primary key,
  at                   timestamptz not null default now(),
  run_id               uuid references public.loop_runs(id) on delete cascade,

  -- stage timings, milliseconds
  release_to_text_ms   integer,   -- key release -> transcript in hand
  first_token_ms       integer,   -- query -> first token from the model
  first_sentence_ms    integer,   -- query -> first complete sentence
  first_audio_ms       integer,   -- query -> first audible syllable
  total_ms             integer not null,

  -- shape of the turn
  sentences            smallint not null default 0,
  tool_calls           smallint not null default 0,
  barge_in             boolean  not null default false,
  rebuilt              boolean  not null default false,  -- the drain had to rebuild

  constraint voice_turns_total_sane      check (total_ms >= 0 and total_ms < 600000),
  constraint voice_turns_stages_ordered  check (
    first_token_ms is null or first_sentence_ms is null
    or first_sentence_ms >= first_token_ms)
);

comment on table public.voice_turns is
  'Per-turn latency for the Desk voice daemon. TIMINGS ONLY — this table has no '
  'text column by design, so it cannot carry speech, a transcript, or case '
  'material. See Rule 4 in the voice repo THREAT_MODEL.md.';

create index if not exists voice_turns_at_idx  on public.voice_turns (at desc);
create index if not exists voice_turns_run_idx on public.voice_turns (run_id);

alter table public.voice_turns enable row level security;

drop policy if exists voice_turns_admin_read on public.voice_turns;
create policy voice_turns_admin_read on public.voice_turns
  for select using (public.has_admin_role());

-- Append-only, like voice_audit.
create or replace function public.tg_voice_turns_immutable()
returns trigger language plpgsql as $$
begin
  raise exception 'voice_turns is append-only';
end $$;

drop trigger if exists voice_turns_no_update on public.voice_turns;
create trigger voice_turns_no_update before update or delete on public.voice_turns
  for each row execute function public.tg_voice_turns_immutable();


-- ---------------------------------------------------------------------------
-- The dashboard RPC.
--
-- One call, one screen. SECURITY DEFINER and gated by is_owner() so the route
-- guard and nav visibility in the admin app stay cosmetic and this is the real
-- boundary — the same shape as owner_dashboard_metrics (087).
--
-- Returns counts, timings and rule names. Never a transcript, never an
-- identifier belonging to a case: voice_audit.asked holds the ACTION and its
-- arguments, never what Joel said, and the free-text columns are not selected
-- here at all.
-- ---------------------------------------------------------------------------

create or replace function public.voice_dashboard_metrics(p_window text default '7d')
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_since   timestamptz;
  v_result  jsonb;
begin
  if not public.is_owner() then
    raise exception 'not authorised' using errcode = '42501';
  end if;

  v_since := case p_window
    when 'today' then date_trunc('day', now())
    when '7d'    then now() - interval '7 days'
    when '30d'   then now() - interval '30 days'
    when 'all'   then '-infinity'::timestamptz
  end;
  -- Fail loud on an unknown window rather than silently widening to everything.
  if v_since is null then
    raise exception 'unknown window %', p_window using errcode = '22023';
  end if;

  select jsonb_build_object(
    'window',       p_window,
    'generated_at', now(),

    -- The last session, whenever it was: a dashboard that shows nothing
    -- because the window is empty is how you miss a daemon that stopped.
    'last_session', coalesce((
      select jsonb_build_object(
        'at',           r.started_at,
        'finished_at',  r.finished_at,
        'status',       r.status,
        'notes',        r.notes,
        'turns',        (select count(*) from public.voice_turns t where t.run_id = r.id),
        'age_minutes',  round(extract(epoch from (now() - r.started_at)) / 60)::int,
        'stale',        (r.status = 'running'
                         and r.started_at < now() - interval '6 hours')
      )
      from public.loop_runs r
      where r.loop = 'desk-voice'
      order by r.started_at desc
      limit 1
    ), 'null'::jsonb),

    'sessions', (
      select jsonb_build_object(
        'total',   count(*),
        'passed',  count(*) filter (where status = 'passed'),
        'failed',  count(*) filter (where status = 'failed'),
        -- A row still marked running and older than six hours is a silent
        -- failure, not a long job.
        'stalled', count(*) filter (where status = 'running'
                                      and started_at < now() - interval '6 hours')
      )
      from public.loop_runs
      where loop = 'desk-voice' and started_at >= v_since
    ),

    'latency', (
      select jsonb_build_object(
        'turns',             count(*),
        'p50_ms',            round(percentile_cont(0.5)  within group (order by total_ms))::int,
        'p95_ms',            round(percentile_cont(0.95) within group (order by total_ms))::int,
        'budget_p50_ms',     1200,
        'budget_p95_ms',     1800,
        'transcribe_p50_ms', round(percentile_cont(0.5) within group (
                               order by coalesce(release_to_text_ms, 0)))::int,
        'first_token_p50_ms', round(percentile_cont(0.5) within group (
                               order by coalesce(first_token_ms, 0)))::int,
        'first_sentence_p50_ms', round(percentile_cont(0.5) within group (
                               order by coalesce(first_sentence_ms - first_token_ms, 0)))::int,
        'first_audio_p50_ms', round(percentile_cont(0.5) within group (
                               order by coalesce(first_audio_ms - first_sentence_ms, 0)))::int,
        'barge_ins',         count(*) filter (where barge_in),
        'rebuilds',          count(*) filter (where rebuilt)
      )
      from public.voice_turns
      where at >= v_since
    ),

    'actions', (
      select jsonb_build_object(
        'allowed',    count(*) filter (where decision = 'allow'),
        'refused',    count(*) filter (where decision = 'deny'),
        'reads',      count(*) filter (where decision = 'allow' and risk = 'low'
                                         and action not like 'queue.%'),
        'approvals',  count(*) filter (where decision = 'allow' and action = 'queue.approve'),
        'rejections', count(*) filter (where decision = 'allow' and action = 'queue.reject'),
        'defers',     count(*) filter (where decision = 'allow' and action = 'queue.defer'),
        'high_risk_approvals', count(*) filter (where decision = 'allow' and risk = 'high'),
        'refusals_spoken',     count(*) filter (where decision = 'deny' and spoken_aloud)
      )
      from public.voice_audit
      where at >= v_since
    ),

    -- What ran, by name. Action names, never arguments.
    'by_action', coalesce((
      select jsonb_object_agg(action, n)
      from (
        select action, count(*) as n
        from public.voice_audit
        where at >= v_since and decision = 'allow'
        group by action order by n desc limit 12
      ) s
    ), '{}'::jsonb),

    -- The security signal. A spike in bash.forbidden_verb or read.secret means
    -- something is trying things, and it is the first thing worth seeing.
    'refusals_by_rule', coalesce((
      select jsonb_object_agg(outcome, n)
      from (
        select outcome, count(*) as n
        from public.voice_audit
        where at >= v_since and decision = 'deny' and outcome is not null
        group by outcome order by n desc limit 12
      ) s
    ), '{}'::jsonb)
  )
  into v_result;

  return v_result;
end $$;

revoke all on function public.voice_dashboard_metrics(text) from public, anon;
grant execute on function public.voice_dashboard_metrics(text) to authenticated;

comment on function public.voice_dashboard_metrics(text) is
  'Single data source for the owner dashboard voice section. is_owner() gated; '
  'returns counts, timings and rule names only — no transcript, no case data.';

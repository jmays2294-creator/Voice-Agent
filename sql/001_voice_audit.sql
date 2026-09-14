-- Desk — voice audit. Rule 7.
--
-- Every voice session writes a loop_runs row. Every action the allowlist
-- permitted writes a voice_audit row with source='voice'. Every action the
-- guard denied is written here too, with decision='deny' and the rule that
-- refused it, so a refusal is reconstructable months later.
--
-- No case material reaches this table: desk.guard.redact runs over every value
-- before it leaves the Mac. The trigger below is the backstop for that, and it
-- raises rather than scrubs — a row that would have carried a WCB number is a
-- bug worth seeing, not one worth silently fixing.

create table if not exists public.voice_audit (
  id            bigserial primary key,
  at            timestamptz not null default now(),
  source        text        not null default 'voice',
  run_id        uuid        references public.loop_runs(id) on delete set null,

  -- what was asked, what ran, what changed
  action        text        not null,
  risk          text        not null check (risk in ('low','medium','high','denied')),
  asked         text,
  argv          jsonb,
  outcome       text,
  changed       text,

  -- allow or deny, and why
  decision      text        not null check (decision in ('allow','deny')),
  reason        text,
  spoken_aloud  boolean     not null default false,

  constraint voice_audit_source_ck check (source = 'voice')
);

comment on table public.voice_audit is
  'Every action the voice daemon took or was refused. Append-only: a silent '
  'denial teaches nobody, a silent approval is unreconstructable. Redacted '
  'before it leaves the Mac; tg_voice_audit_guard is the backstop.';

create index if not exists voice_audit_at_idx      on public.voice_audit (at desc);
create index if not exists voice_audit_decision_idx on public.voice_audit (decision, at desc);
create index if not exists voice_audit_run_idx     on public.voice_audit (run_id);

-- Append-only, like admin_audit_log and lead_audit_log.
create or replace function public.tg_voice_audit_immutable()
returns trigger language plpgsql as $$
begin
  raise exception 'voice_audit is append-only';
end $$;

drop trigger if exists voice_audit_no_update on public.voice_audit;
create trigger voice_audit_no_update before update or delete on public.voice_audit
  for each row execute function public.tg_voice_audit_immutable();

-- Backstop against case material. Raises rather than scrubs, matching
-- tg_workspace_telemetry_guard.
create or replace function public.tg_voice_audit_guard()
returns trigger language plpgsql as $$
begin
  if new.asked ~ '\m[A-Z]\d{7,8}\M' or new.changed ~ '\m[A-Z]\d{7,8}\M' then
    raise exception 'voice_audit row carries something shaped like a WCB number';
  end if;
  if new.asked ~ '\d{3}-\d{2}-\d{4}' or new.changed ~ '\d{3}-\d{2}-\d{4}' then
    raise exception 'voice_audit row carries something shaped like an SSN';
  end if;
  if new.asked ~* '(sk|pk)-[A-Za-z0-9_-]{16,}' or new.asked ~* 'eyJ[A-Za-z0-9_-]{8,}\.' then
    raise exception 'voice_audit row carries something shaped like a credential';
  end if;
  return new;
end $$;

drop trigger if exists voice_audit_guard on public.voice_audit;
create trigger voice_audit_guard before insert on public.voice_audit
  for each row execute function public.tg_voice_audit_guard();

-- Owner-only. The daemon writes with the service role, which bypasses RLS.
alter table public.voice_audit enable row level security;

drop policy if exists voice_audit_admin_read on public.voice_audit;
create policy voice_audit_admin_read on public.voice_audit
  for select using (public.has_admin_role());

-- The dashboard's voice section.
create or replace view public.voice_session_summary as
select
  date_trunc('day', at)                                         as day,
  count(*) filter (where decision = 'allow')                    as actions,
  count(*) filter (where decision = 'deny')                     as refusals,
  count(*) filter (where decision = 'allow' and risk = 'high')   as high_risk_approvals,
  count(distinct run_id)                                        as sessions
from public.voice_audit
group by 1
order by 1 desc;

comment on view public.voice_session_summary is
  'Owner dashboard voice section: actions, refusals and voice approvals by day.';

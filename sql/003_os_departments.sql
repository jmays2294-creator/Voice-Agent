-- Comp Desk OS: the voice and owner_app departments.
--
-- Applied to the live project on 2026-09-14 via Supabase migrations. Recorded
-- here so the schema these loops depend on is reproducible from this repo,
-- even though the OS schema's home is thecompdesk-app.
--
-- Three of these statements exist because of mistakes worth keeping visible:
-- `create table (like ... including all)` clones CHECK constraints too, and the
-- cloned ones enumerate app_improvements' vocabularies. The new tables defaulted
-- to values those lists reject, so every insert would have failed — unattended,
-- at 3am, which is the exact silent-failure shape this department is built
-- against. Audit every constraint after a LIKE clone; do not discover them one
-- failed insert at a time.

-- 1. Departments are a closed set, enforced on three tables. Widen together or
--    loop_runs rejects the rows the new schedules write.
alter table public.loop_runs   drop constraint if exists loop_runs_dept_check;
alter table public.loop_runs   add  constraint loop_runs_dept_check
  check (dept is null or dept = any (array[
    'product','web','growth','chief_of_staff','voice','owner_app']));

alter table public.os_schedule drop constraint if exists os_schedule_dept_check;
alter table public.os_schedule add  constraint os_schedule_dept_check
  check (dept is null or dept = any (array[
    'product','web','growth','chief_of_staff','voice','owner_app']));

alter table public.registry    drop constraint if exists registry_owner_dept_check;
alter table public.registry    add  constraint registry_owner_dept_check
  check (owner_dept = any (array[
    'product','web','growth','chief_of_staff','voice','owner_app']));

alter table public.registry    drop constraint if exists registry_surface_check;
alter table public.registry    add  constraint registry_surface_check
  check (surface = any (array[
    'worker','attorney','public','admin','desk','owner_app']));

-- 2. Two backlogs, structurally identical to app_improvements so the four-stage
--    lifecycle and the Gate A/B/C columns match and the owner dashboard can
--    union all three.
create table if not exists public.voice_improvements
  (like public.app_improvements including all);
alter table public.voice_improvements alter column dept    set default 'voice';
alter table public.voice_improvements alter column surface set default 'desk';
alter table public.voice_improvements alter column source  set default 'voice_sweep';

create table if not exists public.owner_app_improvements
  (like public.app_improvements including all);
alter table public.owner_app_improvements alter column dept    set default 'owner_app';
alter table public.owner_app_improvements alter column surface set default 'ios';
alter table public.owner_app_improvements alter column source  set default 'owner_sweep';

-- 3. The cloned vocabularies, corrected for these surfaces.
alter table public.voice_improvements drop constraint if exists app_improvements_surface_ck;
alter table public.voice_improvements add  constraint voice_improvements_surface_ck
  check (surface = any (array['desk','infra','both']));
alter table public.voice_improvements drop constraint if exists app_improvements_source_ck;
alter table public.voice_improvements add  constraint voice_improvements_source_ck
  check (source = any (array['voice_sweep','mac_verify','research','manual',
                             'ui_audit','deepdive','dept_head','peer_review','owner']));
alter table public.voice_improvements drop constraint if exists app_improvements_dept_ck;
alter table public.voice_improvements add  constraint voice_improvements_dept_ck
  check (dept = 'voice');

alter table public.owner_app_improvements drop constraint if exists app_improvements_surface_ck;
alter table public.owner_app_improvements add  constraint owner_app_improvements_surface_ck
  check (surface = any (array['owner_app','infra','both']));
alter table public.owner_app_improvements drop constraint if exists app_improvements_source_ck;
alter table public.owner_app_improvements add  constraint owner_app_improvements_source_ck
  check (source = any (array['owner_sweep','mac_verify','research','manual',
                             'ui_audit','deepdive','dept_head','peer_review','owner']));
alter table public.owner_app_improvements drop constraint if exists app_improvements_dept_ck;
alter table public.owner_app_improvements add  constraint owner_app_improvements_dept_ck
  check (dept = 'owner_app');

-- NOTE on auto-shipping, deliberately left alone: the inherited check reads
--   NOT auto_shippable OR (dept IN ('web','chief_of_staff') AND risk_class <> 'high')
-- With dept pinned above, auto_shippable is impossible in both tables. That is
-- the desired answer and it is stronger than the trigger below, which stays as
-- the place the reason is written down.
create or replace function public.tg_high_risk_never_autoships()
returns trigger language plpgsql as $$
begin
  if new.risk_class = 'high' and new.auto_shippable then
    raise exception 'risk_class=high can never be auto_shippable (%)', new.title;
  end if;
  return new;
end $$;

drop trigger if exists voice_improvements_no_autoship on public.voice_improvements;
create trigger voice_improvements_no_autoship before insert or update
  on public.voice_improvements for each row
  execute function public.tg_high_risk_never_autoships();

drop trigger if exists owner_app_improvements_no_autoship on public.owner_app_improvements;
create trigger owner_app_improvements_no_autoship before insert or update
  on public.owner_app_improvements for each row
  execute function public.tg_high_risk_never_autoships();

alter table public.voice_improvements     enable row level security;
alter table public.owner_app_improvements enable row level security;

drop policy if exists voice_improvements_admin on public.voice_improvements;
create policy voice_improvements_admin on public.voice_improvements
  for all using (public.has_admin_role()) with check (public.has_admin_role());

drop policy if exists owner_app_improvements_admin on public.owner_app_improvements;
create policy owner_app_improvements_admin on public.owner_app_improvements
  for all using (public.has_admin_role()) with check (public.has_admin_role());

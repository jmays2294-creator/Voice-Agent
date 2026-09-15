-- Touch trigger for voice_improvements.updated_at.
--
-- NOT APPLIED by any loop. This file documents the migration; running it
-- against the live project is Joel's step, not cd-voice-build's or
-- cd-voice-review's. Neither loop may run DDL against voice_improvements —
-- only Joel, by hand, decides when this lands.
--
-- Why it exists: the review-queue selection in ops/loops/voice-review.md
-- now compares gate_b_at against implemented_at to tell a stale verdict from
-- a current one. That comparison is only meaningful if updated_at (and any
-- column derived from it) actually reflects the row's last write, which
-- Postgres does not do for you — an application-set timestamp column drifts
-- the moment someone updates the row through the SQL editor instead of the
-- normal write path.

create or replace function public.tg_voice_improvements_touch()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists voice_improvements_touch on public.voice_improvements;
create trigger voice_improvements_touch before update
  on public.voice_improvements for each row
  execute function public.tg_voice_improvements_touch();

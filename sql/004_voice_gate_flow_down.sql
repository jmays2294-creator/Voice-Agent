-- Reverses sql/004_voice_gate_flow.sql.
--
-- Kept because the forward migration installs a trigger that rewrites columns
-- on every update to voice_improvements. If that turns out to be wrong, the
-- way back should already be written down rather than composed under pressure.
--
-- gate_b_history is deliberately NOT dropped by default: it holds Gate B
-- findings that exist nowhere else once a rebuild has archived them. Dropping
-- the column destroys them. The statement is here, commented, so removing it
-- is a deliberate act.

drop view if exists public.voice_stuck_items;
drop view if exists public.voice_gate_b_queue;

drop trigger if exists voice_improvements_gate_flow on public.voice_improvements;
drop function if exists public.tg_voice_improvements_gate_flow();

-- Destroys archived Gate B findings. Uncomment only if you mean it.
-- alter table public.voice_improvements
--   drop constraint if exists voice_improvements_gate_b_history_is_array_ck;
-- alter table public.voice_improvements drop column if exists gate_b_history;

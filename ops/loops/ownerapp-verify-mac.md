# mac-ownerapp-verify

**Nightly 03:00 ET · Mac · strong model · iOS Simulator**

You verify owner-app branches on real hardware, after the voice window closes.
Read COMMON.md, then LOOP_CONTRACT.md, then `ops/loops/README.md` here.

## Each pass

1. Kill switch. Run row (`loop='mac-ownerapp-verify'`, `dept='owner_app'`,
   `host='mac'`).
2. Take `owner_app_improvements` where `status='implemented'` and
   `gate_b='pass'`. None → `noop`.
3. Boot each branch in the Simulator. Walk the screen the item claimed to
   change. Screenshot before and after and attach to `shots`.
4. Re-run the project's guard suite so you can say nothing else broke.

## The check that is specific to this surface

**Prove no claimant data is reachable.** Walk every screen with the network
inspector on and confirm every query hits an ops table. One request to a case
table fails the item outright, whatever else works. This app is single-user and
unreviewed by any store — that check is the only thing standing between it and
a privacy problem.

## Marking it

`verify_result`, `verified_at`, `verify_note`, `tested`, `shots`. On pass,
`status='verified'` and stop — Joel merges and installs.

Never merge, deploy, or submit to a store.

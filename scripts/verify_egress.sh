#!/bin/sh
# Rule 3 acceptance: exactly three hosts reachable, and a fourth unreachable.
# The fourth is the test that matters — 1 through 3 passing proves nothing.
set -u
SUPABASE_HOST="${DESK_SUPABASE_HOST:-}"
FAIL=0

probe() {
  host=$1; port=$2; want=$3; label=$4
  if command -v nc >/dev/null 2>&1; then
    if nc -z -G 4 -w 4 "$host" "$port" >/dev/null 2>&1; then got=reachable; else got=blocked; fi
  else
    if curl -s -m 5 -o /dev/null "https://$host" 2>/dev/null; then got=reachable; else got=blocked; fi
  fi
  if [ "$got" = "$want" ]; then
    printf '  PASS  %-46s %s\n' "$label" "$got"
  else
    printf '  FAIL  %-46s %s (expected %s)\n' "$label" "$got" "$want"; FAIL=1
  fi
}

echo "Egress allowlist (run as the daemon's group: sg _desk -c 'sh scripts/verify_egress.sh')"
echo "======================================================================"
probe api.anthropic.com 443 reachable "api.anthropic.com:443 (the model)"
if [ -n "$SUPABASE_HOST" ]; then
  probe "$SUPABASE_HOST" 443 reachable "$SUPABASE_HOST:443 (loop state and audit)"
else
  echo "  SKIP  supabase host not set (export DESK_SUPABASE_HOST)"
fi
probe github.com 443 reachable "github.com:443 (read-only fetch)"
echo
echo "The one that matters:"
probe example.com 443 blocked "example.com:443 (a fourth host)"
probe 1.1.1.1 443 blocked "1.1.1.1:443 (a bare address)"
probe api.elevenlabs.io 443 blocked "api.elevenlabs.io:443 (no cloud voice)"
echo
probe github.com 80 blocked "github.com:80 (plain HTTP)"
echo
if [ "$FAIL" -eq 0 ]; then
  echo "PASS — the allowlist is installed and enforcing."
else
  echo "FAIL — the rule set is not enforcing. See docs/EGRESS.md; do not widen it."
fi
exit $FAIL

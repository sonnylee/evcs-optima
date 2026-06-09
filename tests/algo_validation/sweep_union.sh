#!/usr/bin/env bash
#
# tests/algo_validation/sweep_union.sh
# Run multi-seed exploration sweep, then compute cross-seed coverage union.
#
# Usage:
#   ./sweep_union.sh                        # 10 default seeds, eps=0.2
#   ./sweep_union.sh 1 7 42 100             # custom seed list
#   EVCS_EPSILON=0.3 ./sweep_union.sh       # higher exploration rate
#   SWEEP_OUT=~/my_sweep ./sweep_union.sh   # custom output dir
#
# Output:
#   $SWEEP_OUT/visited_<seed>.json   per-seed visited-set dumps
#   $SWEEP_OUT/pytest_<seed>.log     per-seed pytest stdout (debug)
#   $SWEEP_OUT/union_report.txt      final union report (also printed)

set -uo pipefail   # not -e: pytest failure on one seed should not abort the sweep

# --- Defaults ---------------------------------------------------------------
DEFAULT_SEEDS=(1 7 42 100 1000 12345 67890 99999 314159 271828)
EPSILON="${EVCS_EPSILON:-0.2}"
OUT_DIR="${SWEEP_OUT:-/tmp/sweep_union}"

if [ $# -gt 0 ]; then
  SEEDS=("$@")
else
  SEEDS=("${DEFAULT_SEEDS[@]}")
fi

# --- Setup ------------------------------------------------------------------
mkdir -p "$OUT_DIR"
rm -f "$OUT_DIR"/visited_*.json "$OUT_DIR"/pytest_*.log "$OUT_DIR"/union_report.txt

cat <<EOF
=== Multi-seed exploration sweep ===
Seeds:    ${SEEDS[*]}
Count:    ${#SEEDS[@]}
Epsilon:  $EPSILON
Output:   $OUT_DIR
=====================================

EOF

# --- Per-seed runs ----------------------------------------------------------
START_TIME=$SECONDS
fail_count=0
for seed in "${SEEDS[@]}"; do
  printf "  seed=%-8s ... " "$seed"
  SECONDS_BEFORE=$SECONDS

  if EVCS_SEED="$seed" \
     EVCS_EPSILON="$EPSILON" \
     EVCS_DUMP_VISITED="$OUT_DIR/visited_$seed.json" \
     pytest tests/algo_validation/test_exploration.py -k exploration -s \
       > "$OUT_DIR/pytest_$seed.log" 2>&1; then
    elapsed=$((SECONDS - SECONDS_BEFORE))
    visited=$(grep -oE "visited=[0-9]+/766" "$OUT_DIR/pytest_$seed.log" | head -1 || echo "visited=?")
    termination=$(grep -oE "termination=[a-z_>=0-9]+" "$OUT_DIR/pytest_$seed.log" | head -1 || echo "")
    printf "PASS  %-16s  %-26s  (%ds)\n" "$visited" "$termination" "$elapsed"
  else
    elapsed=$((SECONDS - SECONDS_BEFORE))
    printf "FAIL  (see %s/pytest_%s.log)  (%ds)\n" "$OUT_DIR" "$seed" "$elapsed"
    fail_count=$((fail_count + 1))
  fi
done

TOTAL_TIME=$((SECONDS - START_TIME))

echo ""
echo "=== Sweep done in ${TOTAL_TIME}s.  pytest failures: $fail_count  ==="
echo ""

# --- Union ------------------------------------------------------------------
if ls "$OUT_DIR"/visited_*.json >/dev/null 2>&1; then
  python tests/algo_validation/union_coverage.py "$OUT_DIR"/visited_*.json \
    | tee "$OUT_DIR/union_report.txt"
else
  echo "No visited JSON dumps produced; nothing to union." >&2
  exit 1
fi
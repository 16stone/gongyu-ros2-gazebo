#!/usr/bin/env bash
set -euo pipefail
checkout=${1:?B1 worktree}
evidence=${2:?evidence output root}
round=${3:?new round ID}
cd "$checkout"
export GONGYU_RUNS_ROOT="$evidence/runs"
export GONGYU_PHYS=1 GONGYU_NO_RENDER=1 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 LP_NUM_THREADS=2 GONGYU_WALL_LIMIT=120
export PYTHONDONTWRITEBYTECODE=1
export GONGYU_B1_CPU="${GONGYU_B1_CPU:-28,29}"
export GONGYU_B1_TRIAL_ROUND="$round"
flock -w 1800 "$HOME/pandaoxi/gongyu-enhance-sim.lock" bash -s <<'TRIALS'
for treatment in coverage-astar-1 lowobs-astar-0 lowobs-astar-1 open-dijkstra-1 open-astar-1 narrow-dijkstra-1 narrow-astar-1; do
  IFS=- read -r layout planner low <<< "$treatment"
  GONGYU_B1_PLANNER="$planner" GONGYU_B1_LOW="$low" nice -n 10 taskset -c "$GONGYU_B1_CPU" bash webots/tools/run_webots.sh \
    "web_b1_phaseb_$layout" "b1-$treatment-$GONGYU_B1_TRIAL_ROUND" < /dev/null || echo "FAILED $treatment rc=$?"
done
TRIALS

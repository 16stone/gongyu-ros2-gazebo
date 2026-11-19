#!/usr/bin/env bash
# Run one Phase C condition through the existing private-display launcher.
set -euo pipefail
case "${1:-}" in
  truth) export GONGYU_FEEDBACK_MODE=truth GONGYU_UAV_OCCLUDED=0 GONGYU_UAV_DROPOUT=0 ;;
  visible) export GONGYU_FEEDBACK_MODE=sensor GONGYU_UAV_OCCLUDED=0 GONGYU_UAV_DROPOUT=0 ;;
  occluded) export GONGYU_FEEDBACK_MODE=sensor GONGYU_UAV_OCCLUDED=1 GONGYU_UAV_DROPOUT=0 ;;
  dropout) export GONGYU_FEEDBACK_MODE=sensor GONGYU_UAV_OCCLUDED=0 GONGYU_UAV_DROPOUT=1 ;;
  *) echo 'Usage: run_uav_course.sh {truth|visible|occluded|dropout} RUN_ID' >&2; exit 2 ;;
esac
[[ $# -eq 2 && "$2" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || {
  echo 'Provide a new RUN_ID with letters, digits, dots, underscores or hyphens.' >&2
  exit 2
}
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
export GONGYU_RUNS_ROOT="${GONGYU_RUNS_ROOT:-$HOME/pandaoxi/gongyu-enhance-evidence/uav/runs}"
export GONGYU_NO_RENDER=1 GONGYU_PHYS=1 GONGYU_SEED=19 LP_NUM_THREADS=2 OMP_NUM_THREADS=1
export GONGYU_WALL_LIMIT="${GONGYU_WALL_LIMIT:-180}"
cpus=$(python3 -c 'import os; print(",".join(map(str, sorted(os.sched_getaffinity(0))[:2])))')
(
  flock -w 1800 9
  taskset -c "$cpus" nice -n 15 bash webots/tools/run_webots.sh web_course_b3_flight "$2" "$@"
) 9>"$HOME/pandaoxi/gongyu-enhance-sim.lock"

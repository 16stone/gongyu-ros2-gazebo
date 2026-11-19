#!/usr/bin/env bash
# Run one Webots episode on a headless CPU host, then close the receipt.
# Paths default to a sibling layout; override any of them through the environment.
set -euo pipefail
SCENE=${1:?scene world name}
RUNID=${2:?new run id}
shift 2
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WEBOTS=${GONGYU_WEBOTS_HOME:-$HOME/pandaoxi/webots}
XR=${GONGYU_XVFB_ROOT:-$HOME/pandaoxi/xvfb_root}
RUNROOT=${GONGYU_RUNS_ROOT:-$HOME/pandaoxi/gongyu-webots-runs}/$RUNID
if [ -e "$RUNROOT" ]; then echo "RUN_ID_EXISTS: $RUNID"; exit 2; fi
mkdir -p -m 700 "$RUNROOT"/{bus,result,evidence}
export LD_LIBRARY_PATH="$XR/usr/lib/x86_64-linux-gnu:$WEBOTS/lib/webots:${LD_LIBRARY_PATH:-}"
export LIBGL_ALWAYS_SOFTWARE=1
unset QT_QPA_PLATFORM
export GONGYU_WEBOTS_COMMON="$REPO/webots/common"
export GONGYU_RUN_DIR="$RUNROOT"
export GONGYU_SCENE="$SCENE"
# Allocate a private display. Only stop the X server spawned by this run.
"$XR/usr/bin/Xvfb" -displayfd 3 -screen 0 1280x1024x24 -nolisten tcp \
    3>"$RUNROOT/display.txt" >"$RUNROOT/xvfb.log" 2>&1 &
display_pid=$!
trap 'kill "$display_pid" 2>/dev/null || true' EXIT
for _i in $(seq 1 40); do
  test -s "$RUNROOT/display.txt" && break
  sleep 0.25
done
if ! test -s "$RUNROOT/display.txt"; then
  echo "DISPLAY_NOT_READY"; exit 9
fi
export DISPLAY=":$(cat "$RUNROOT/display.txt")"
if ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
  echo "DISPLAY_NOT_READY"; exit 9
fi
printf 'run=%s\nscene=%s\nplatform=amax-cpu-webots-r2025a\n' "$RUNID" "$SCENE" > "$RUNROOT/environment.txt"
printf 'physical_actuation=%s\nloc_mode=%s\nfeedback_mode=%s\nseed=%s\n' "${GONGYU_PHYS:-0}" "${GONGYU_LOC:-gps}" "${GONGYU_FEEDBACK_MODE:-sensor}" "${GONGYU_SEED:-0}" >> "$RUNROOT/environment.txt"
printf '%s\n' "$*" >> "$RUNROOT/environment.txt"
git -C "$REPO" rev-parse HEAD >"$RUNROOT/source.commit"
(cd "$REPO" && find webots/controllers webots/common -name '*.py' -print0 |
    sort -z | xargs -0 sha256sum) >"$RUNROOT/source.sha256"
sha256sum "$REPO/webots/worlds/$SCENE.wbt" "$REPO/webots/config/scenario_medium.json" > "$RUNROOT/scene.sha256"
cd "$REPO/webots/worlds"
set +e
timeout "${GONGYU_WALL_LIMIT:-1800}" "$WEBOTS/webots" --mode=fast ${GONGYU_NO_RENDER:+--no-rendering} --batch "$SCENE.wbt" >"$RUNROOT/console.log" 2>&1
RC=$?
set -e
echo "webots_exit=$RC" >> "$RUNROOT/environment.txt"
if (( RC != 0 )); then exit "$RC"; fi
if [ -f "$RUNROOT/shutdown.json" ]; then
  cp "$RUNROOT/shutdown.json" "$RUNROOT/result/shutdown.json" 2>/dev/null || true
fi
python3 - "$RUNROOT" <<'PY'
import json, os, sys
r=sys.argv[1]
shutdown=os.path.join(r,'shutdown.json')
if not os.path.isfile(shutdown) or json.load(open(shutdown)).get('status') != 'COMPLETE':
    print('SHUTDOWN_INCOMPLETE'); sys.exit(4)
m=os.path.join(r,'result','metrics.json')
if not os.path.exists(m):
    print('METRICS_MISSING'); sys.exit(3)
d=json.load(open(m))
print('RUN_CLOSED', d.get('on_time'), d.get('total'), 'window', d.get('full_window'), 'violations', d.get('violation_count'))
PY
echo "RUN_DIR=$RUNROOT"

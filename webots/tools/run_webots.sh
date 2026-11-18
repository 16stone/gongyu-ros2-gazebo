#!/usr/bin/env bash
# Run one Webots episode on amax with CPU software rendering, then close the receipt.
set -euo pipefail
SCENE=${1:?scene world name}
RUNID=${2:?new run id}
shift 2
REPO=/home/liujingzhi/pandaoxi/gongyu-ros2-gazebo
WEBOTS=/home/liujingzhi/pandaoxi/webots
XR=/home/liujingzhi/pandaoxi/xvfb_root
RUNROOT=/home/liujingzhi/pandaoxi/gongyu-webots-runs/$RUNID
if [ -e "$RUNROOT" ]; then echo "RUN_ID_EXISTS: $RUNID"; exit 2; fi
mkdir -p -m 700 "$RUNROOT"/{bus,result,evidence}
export LD_LIBRARY_PATH="$XR/usr/lib/x86_64-linux-gnu:$WEBOTS/lib/webots:${LD_LIBRARY_PATH:-}"
export LIBGL_ALWAYS_SOFTWARE=1
export DISPLAY=:99
unset QT_QPA_PLATFORM
export GONGYU_WEBOTS_COMMON="$REPO/webots/common"
export GONGYU_RUN_DIR="$RUNROOT"
export GONGYU_SCENE="$SCENE"
if ! pgrep -f 'Xvfb :99' >/dev/null; then
  "$XR/usr/bin/Xvfb" :99 -screen 0 1280x1024x24 -nolisten tcp >"$RUNROOT/xvfb.log" 2>&1 &
fi
# wait until display socket is ready
for _i in $(seq 1 40); do
  [ -S /tmp/.X11-unix/X99 ] && break
  sleep 0.25
done
if ! xdpyinfo -display :99 >/dev/null 2>&1; then
  echo "DISPLAY_NOT_READY"; exit 9
fi
printf 'run=%s\nscene=%s\nplatform=amax-cpu-webots-r2025a\n' "$RUNID" "$SCENE" > "$RUNROOT/environment.txt"
printf 'physical_actuation=%s\nloc_mode=%s\nfeedback_mode=%s\nseed=%s\n' "${GONGYU_PHYS:-0}" "${GONGYU_LOC:-gps}" "${GONGYU_FEEDBACK_MODE:-sensor}" "${GONGYU_SEED:-0}" >> "$RUNROOT/environment.txt"
printf '%s\n' "$*" >> "$RUNROOT/environment.txt"
sha256sum "$REPO/webots/worlds/$SCENE.wbt" "$REPO/webots/config/scenario_medium.json" > "$RUNROOT/scene.sha256"
cd "$REPO/webots/worlds"
set +e
timeout "${GONGYU_WALL_LIMIT:-1800}" "$WEBOTS/webots" --mode=fast ${GONGYU_NO_RENDER:+--no-rendering} --batch "$SCENE.wbt" >"$RUNROOT/console.log" 2>&1
RC=$?
set -e
echo "webots_exit=$RC" >> "$RUNROOT/environment.txt"
if [ -f "$RUNROOT/shutdown.json" ]; then
  cp "$RUNROOT/shutdown.json" "$RUNROOT/result/shutdown.json" 2>/dev/null || true
fi
python3 - "$RUNROOT" <<'PY'
import json, os, sys
r=sys.argv[1]
m=os.path.join(r,'result','metrics.json')
if not os.path.exists(m):
    print('METRICS_MISSING'); sys.exit(3)
d=json.load(open(m))
print('RUN_CLOSED', d.get('on_time'), d.get('total'), 'window', d.get('full_window'), 'violations', d.get('violation_count'))
PY
echo "RUN_DIR=$RUNROOT"

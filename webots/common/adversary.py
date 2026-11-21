"""Red-team adversary behaviours and blue-team countermeasures for the course range.

Two adversary behaviours are modelled on top of the shared-corridor course:

* corridor hoarding: a red carrier claims the corridor turn before it can use it
  and keeps the grant idle, so the blue carrier queued behind it cannot leave;
* replay spoofing: the red aircraft loiters near the blue observer, records its
  camera frames, and later re-broadcasts an old frame under a fresh timestamp
  when the blue carrier asks for an observation.

The matching blue countermeasures are

* a fixed response-threshold challenge (Bonabeau et al., 1998): the waiting
  carrier accumulates stimulus while the grant ahead of it stays idle and
  challenges with probability s^2 / (s^2 + theta^2); the arbiter revokes the
  grant only after it verifies from truth motion that the holder is idle and
  outside the corridor;
* frame authentication: the blue observer appends an HMAC over the sender,
  sample time, image signature and frame size; the gate drops any frame whose
  tag does not verify.
"""

import hashlib
import hmac
import math
from random import Random


# ---------------------------------------------------------------- authentication

def frame_digest(key, record):
    """HMAC-SHA256 tag over the fields a receiver relies on."""
    message = '%s|%d|%s|%d' % (
        record.get('actor'), int(record.get('t_ms', -1)),
        record.get('image_signature'), int(record.get('camera_bytes', 0)))
    return hmac.new(key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).hexdigest()[:32]


def sign_frame(key, record):
    signed = dict(record)
    signed['mac'] = frame_digest(key, record)
    return signed


def verify_frame(key, record):
    tag = record.get('mac')
    if not isinstance(tag, str):
        return False
    return hmac.compare_digest(tag, frame_digest(key, record))


# ---------------------------------------------------------------- response threshold

class ResponseThreshold:
    """Fixed response-threshold rule for contesting an idle corridor grant.

    The stimulus grows by ``rate`` per evaluation while the demand is unmet and
    is reset when the demand disappears.  The threshold shrinks as the waiting
    carrier's deadline slack shrinks, so an urgent carrier responds sooner.
    """

    def __init__(self, *, theta_min_s=2.0, theta_max_s=12.0, slack_ref_s=240.0,
                 rate=1.0, seed=0):
        if not 0 < theta_min_s <= theta_max_s:
            raise ValueError('threshold bounds must be positive and ordered')
        self.theta_min_s = theta_min_s
        self.theta_max_s = theta_max_s
        self.slack_ref_s = slack_ref_s
        self.rate = rate
        self.random = Random(seed)
        self.stimulus = 0.0

    def threshold(self, slack_s):
        ratio = max(0.0, min(1.0, slack_s / self.slack_ref_s))
        return self.theta_min_s + (self.theta_max_s - self.theta_min_s) * ratio

    @staticmethod
    def probability(stimulus, theta):
        if stimulus <= 0:
            return 0.0
        return stimulus * stimulus / (stimulus * stimulus + theta * theta)

    def reset(self):
        self.stimulus = 0.0

    def step(self, demand, slack_s):
        """Advance one evaluation; return (respond, stimulus, theta, probability)."""
        if not demand:
            self.reset()
            return False, 0.0, self.threshold(slack_s), 0.0
        self.stimulus += self.rate
        theta = self.threshold(slack_s)
        p = self.probability(self.stimulus, theta)
        return self.random.random() < p, self.stimulus, theta, p


class IdleMonitor:
    """Decide from truth samples whether a grant holder is idle (no travel, no turning)."""

    def __init__(self, *, window_ms=2000, still_m=0.05, still_rad=0.05):
        self.window_ms = window_ms
        self.still_m = still_m
        self.still_rad = still_rad
        self.samples = []

    def reset(self):
        self.samples = []

    def add(self, t_ms, xy, yaw=0.0):
        self.samples.append((t_ms, xy, yaw))
        while self.samples and t_ms - self.samples[0][0] > self.window_ms:
            self.samples.pop(0)

    def idle(self):
        if len(self.samples) < 2 or self.samples[-1][0] - self.samples[0][0] < self.window_ms * 0.9:
            return False
        _, (x0, y0), yaw0 = self.samples[0]
        for _, (x, y), yaw in self.samples:
            turn = abs(math.atan2(math.sin(yaw - yaw0), math.cos(yaw - yaw0)))
            if math.hypot(x - x0, y - y0) > self.still_m or turn > self.still_rad:
                return False
        return True


# ---------------------------------------------------------------- replay attacker

class ReplayAttacker:
    """Red aircraft logic: intercept frames in range, replay the oldest on request."""

    def __init__(self, *, intercept_range_m=8.0, inject_range_m=10.0, min_age_ms=20000):
        self.intercept_range_m = intercept_range_m
        self.inject_range_m = inject_range_m
        self.min_age_ms = min_age_ms
        self.recorded = []
        self.handled_requests = set()

    def observe(self, own_xy, frame):
        """Record a broadcast frame if the sender is within interception range."""
        pose = frame.get('sensor_pose')
        if not pose or not frame.get('camera_bytes'):
            return False
        if math.hypot(own_xy[0] - pose[0], own_xy[1] - pose[1]) > self.intercept_range_m:
            return False
        if self.recorded and self.recorded[-1]['t_ms'] == frame['t_ms']:
            return False
        self.recorded.append(dict(frame))
        return True

    def forge(self, now_ms, own_xy, request, target_xy):
        """Return a forged frame for a new request, or None."""
        key = request.get('request_id', request.get('t_ms'))
        if key in self.handled_requests:
            return None
        if math.hypot(own_xy[0] - target_xy[0], own_xy[1] - target_xy[1]) > self.inject_range_m:
            return None
        stale = [f for f in self.recorded if now_ms - f['t_ms'] >= self.min_age_ms]
        if not stale:
            return None
        self.handled_requests.add(key)
        original = stale[0]
        forged = dict(original)
        forged['t_ms'] = now_ms
        return forged, original

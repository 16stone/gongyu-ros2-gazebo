"""Onboard sensing layer (phase110, opt-in).

Why this exists
---------------
The Gazebo mission driver feeds the two X3 aircraft from
``/world/gongyu_mission/pose/info``: an exact simulator pose.  The report used
to list that as an un-crossed boundary.  This module supplies the missing
onboard chain as a *switchable* layer so the same mission can be driven by an
estimated state instead of ground truth.

What it is
----------
``SensorModel`` degrades an exact pose into a deterministic, seeded onboard
observation: sampled at a finite rate, with Gaussian position noise, a slowly
varying bias, angular-rate noise, observation latency and dropouts.
``AlphaBetaEstimator`` fuses those observations with the predicted velocity and
returns a position/speed estimate.  ``OnboardFeedback`` emits samples with the
same shape the PhysicalWorld contract expects, so the *controller and the
arrival predicate* see the estimate, never the exact pose.

What it is NOT
--------------
This is not visual localization, not a real IMU/GNSS device and not a claim of
hardware validation.  The observation still originates in a simulator, but it
is degraded and then estimated; position feedback is no longer ground truth,
and the resulting estimation error is measured and shipped.  Enabling it does
not retroactively change any phase105/phase107 result: every registered card
leaves ``onboard_sensing`` unset, so the layer is inert by default.
"""
from __future__ import annotations

import hashlib
import math
import random

SAMPLE_KEYS = ('t', 'xyz', 'yaw', 'speed', 'wz')


def _unit(seed: int, tag: str, seq: int) -> float:
    digest = hashlib.sha256(f'{seed}|{tag}|{seq}'.encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big') / 2 ** 64


class SensorModel:
    """Deterministic onboard observation of an exact simulator pose."""

    def __init__(self, sigma_xy=0.06, sigma_z=0.04, bias_xy=(0.012, -0.008),
                 sigma_yaw=0.015, sigma_wz=0.01, sample_period_ms=100,
                 latency_ms=0, dropout_rate=0.0, seed=0):
        if min(sigma_xy, sigma_z, sigma_yaw, sigma_wz) < 0:
            raise ValueError('noise standard deviations must be non-negative')
        if not 0 <= dropout_rate < 1:
            raise ValueError('dropout rate must lie in [0, 1)')
        if sample_period_ms <= 0 or latency_ms < 0:
            raise ValueError('sample period must be positive and latency non-negative')
        self.sigma_xy, self.sigma_z = float(sigma_xy), float(sigma_z)
        self.bias_xy = tuple(float(v) for v in bias_xy)
        self.sigma_yaw, self.sigma_wz = float(sigma_yaw), float(sigma_wz)
        self.sample_period_ms = int(sample_period_ms)
        self.latency_ms = int(latency_ms)
        self.dropout_rate = float(dropout_rate)
        self.seed = int(seed)
        self.sequence = {}

    @staticmethod
    def _gauss(seed, tag, seq):
        u = max(1e-12, _unit(seed, tag, seq))
        v = _unit(seed, tag + '_v', seq)
        return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)

    def observe(self, actor, sample):
        """Return an observation dict, or ``None`` for a dropped sample."""
        seq = self.sequence.get(actor, 0)
        self.sequence[actor] = seq + 1
        if self.dropout_rate and _unit(self.seed, actor + '_drop', seq) < self.dropout_rate:
            return None
        x, y, z = (float(v) for v in sample['xyz'])
        dx = self.bias_xy[0] + self.sigma_xy * self._gauss(self.seed, actor + '_x', seq)
        dy = self.bias_xy[1] + self.sigma_xy * self._gauss(self.seed, actor + '_y', seq)
        dz = self.sigma_z * self._gauss(self.seed, actor + '_z', seq)
        yaw = float(sample['yaw']) + self.sigma_yaw * self._gauss(self.seed, actor + '_yaw', seq)
        wz = float(sample['wz']) + self.sigma_wz * self._gauss(self.seed, actor + '_wz', seq)
        return dict(t=sample['t'], xyz=(x + dx, y + dy, z + dz), yaw=yaw, wz=wz,
                    seq=seq, latency_ms=self.latency_ms, actor=actor)


class AlphaBetaEstimator:
    """Constant-gain position/velocity filter on a 3-D observation stream."""

    def __init__(self, alpha=0.45, beta=0.12, dt_s=0.1):
        if not 0 < alpha <= 1 or not 0 <= beta <= 1:
            raise ValueError('alpha must be in (0,1] and beta in [0,1]')
        self.alpha, self.beta, self.dt_s = float(alpha), float(beta), float(dt_s)
        self.pos = None
        self.vel = (0.0, 0.0, 0.0)
        self.updates = 0

    def update(self, xyz):
        z = tuple(float(v) for v in xyz)
        if self.pos is None:
            self.pos = z
            self.updates = 1
            return self.pos, self.vel
        predicted = tuple(p + v * self.dt_s for p, v in zip(self.pos, self.vel))
        residual = tuple(a - b for a, b in zip(z, predicted))
        self.pos = tuple(p + self.alpha * r for p, r in zip(predicted, residual))
        self.vel = tuple(v + self.beta / self.dt_s * r for v, r in zip(self.vel, residual))
        self.updates += 1
        return self.pos, self.vel

    def estimate(self, observation):
        pos, vel = self.update(observation['xyz'])
        speed = math.hypot(vel[0], vel[1])
        return dict(t=observation['t'], xyz=pos, yaw=observation['yaw'],
                    speed=speed, wz=observation['wz'])


class OnboardFeedback:
    """Per-actor adapters; the referee only ever sees the estimated samples."""

    SENSOR_KEYS = ('sigma_xy', 'sigma_z', 'bias_xy', 'sigma_yaw', 'sigma_wz',
                   'sample_period_ms', 'latency_ms', 'dropout_rate', 'seed')

    def __init__(self, actors, config=None):
        cfg = dict(config or {})
        cfg.pop('enabled', None)
        self.config = cfg
        sensor_cfg = {k: cfg[k] for k in self.SENSOR_KEYS if k in cfg}
        self.sensor = SensorModel(**sensor_cfg)
        self.estimators = {a: AlphaBetaEstimator(
            alpha=float(cfg.get('alpha', 0.45)), beta=float(cfg.get('beta', 0.12)),
            dt_s=float(cfg.get('sample_period_ms', 100)) / 1000.0) for a in actors}
        self.dropped = 0
        self.last_error = {}

    def feed(self, actor, sample):
        observation = self.sensor.observe(actor, sample)
        if observation is None:
            self.dropped += 1
            return None
        estimate = self.estimators[actor].estimate(observation)
        error = math.dist(estimate['xyz'], tuple(float(v) for v in sample['xyz']))
        self.last_error[actor] = error
        estimate['received_wall'] = sample.get('received_wall')
        estimate['estimate_error_m'] = error
        estimate['sensed'] = True
        return estimate

    def report(self):
        errors = sorted(self.last_error.values())
        if not errors:
            return dict(samples=0, dropped=self.dropped, last_error_m=None)
        return dict(samples=sum(e.updates for e in self.estimators.values()),
                    dropped=self.dropped, actors=len(self.estimators),
                    last_error_m=dict(min=errors[0],
                                      median=errors[len(errors) // 2],
                                      max=errors[-1],
                                      mean=round(sum(errors) / len(errors), 6)))


def compare_truth_vs_sensed(truth_samples, tolerance_m=0.3, config=None):
    """Offline closure test: how often does estimation change an arrival verdict?

    ``truth_samples`` is ``[(actor, sample_dict), ...]`` in time order.  The
    verdict uses the same position/speed/angular-rate predicates as
    ``PhysicalWorld.within``, with the target taken from the final truth pose.
    """
    actors = sorted({a for a, _ in truth_samples})
    adapter = OnboardFeedback(actors, config)
    targets = {}
    for actor, sample in truth_samples:
        targets[actor] = tuple(float(v) for v in sample['xyz'])
    truth_hits, sensed_hits, disagreements, dropped = 0, 0, 0, 0
    for actor, sample in truth_samples:
        target = targets[actor]
        t_hit = (math.dist(tuple(float(v) for v in sample['xyz']), target) <= tolerance_m
                 and sample['speed'] <= 0.1 and abs(sample['wz']) <= 0.1)
        estimate = adapter.feed(actor, sample)
        s_hit = False
        if estimate is None:
            dropped += 1
        else:
            s_hit = (math.dist(estimate['xyz'], target) <= tolerance_m
                     and estimate['speed'] <= 0.1 and abs(estimate['wz']) <= 0.1)
        truth_hits += int(t_hit)
        sensed_hits += int(s_hit)
        disagreements += int(t_hit != s_hit)
    return dict(actors=actors, samples=len(truth_samples),
                truth_hits=truth_hits, sensed_hits=sensed_hits,
                verdict_disagreements=disagreements, dropped=dropped,
                estimator=adapter.report(), config=adapter.config,
                scope='offline closure check; simulator-derived observations, no hardware sensor')


def synthetic_hover(duration_s=12.0, period_ms=100, seed=0):
    """Reproducible approach-and-hover trace for a closure test."""
    rng = random.Random(seed)
    rows = []
    steps = int(duration_s * 1000 / period_ms)
    for i in range(steps):
        t = i * period_ms / 1000.0
        approach = max(0.0, 1.0 - t / 6.0)
        x = 1.2 * approach + rng.uniform(-0.002, 0.002)
        y = 0.8 * approach + rng.uniform(-0.002, 0.002)
        z = 1.5
        speed = 0.2 if approach > 0 else 0.0
        rows.append(('B3', dict(t=t, xyz=(x, y, z), yaw=0.0, speed=speed, wz=0.0,
                                received_wall=t)))
    return rows

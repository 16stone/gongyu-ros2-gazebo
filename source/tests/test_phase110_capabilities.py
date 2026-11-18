"""Phase110 capability-layer unit tests (all opt-in, no registered card changes)."""
import math
import unittest

from gongyu import onboard_sensing as sensing
from gongyu.consensus import QuorumConsensus
from gongyu.real_link import MeasuredLinkProfile, MeasuredNetwork


def fake_measurement(n=64):
    rows = [dict(seq=i, rtt_ms=round(0.5 + (i % 9) * 0.03, 4),
                 dropped=(i == 41), echoed=(i != 41)) for i in range(n)]
    return dict(transport='unit-test synthetic measurement', samples=n,
                observed=n - 1, dropped=1, echoed_intact=n - 1,
                server_received=n - 1,
                rtt_ms=dict(min=0.5, p50=0.62, p95=0.74, p99=0.74, max=0.74, mean=0.62),
                rows=rows, boundary='synthetic; not a hardware measurement')


class TestOnboardSensing(unittest.TestCase):
    def test_deterministic_observations(self):
        a = sensing.SensorModel(seed=7)
        b = sensing.SensorModel(seed=7)
        sample = dict(t=1.0, xyz=(1.0, 2.0, 3.0), yaw=0.2, speed=0.3, wz=0.01)
        self.assertEqual(a.observe('B3', sample), b.observe('B3', sample))

    def test_observation_is_not_ground_truth(self):
        sensor = sensing.SensorModel(seed=3, sigma_xy=0.05)
        sample = dict(t=0.0, xyz=(1.0, 2.0, 3.0), yaw=0.0, speed=0.0, wz=0.0)
        observed = sensor.observe('B3', sample)
        self.assertNotEqual(observed['xyz'], sample['xyz'])
        self.assertLess(math.dist(observed['xyz'], sample['xyz']), 0.5)

    def test_dropout_and_latency_flags(self):
        sample = dict(t=0.0, xyz=(0.0, 0.0, 0.0), yaw=0.0, speed=0.0, wz=0.0)
        self.assertIsNone(sensing.SensorModel(seed=1, dropout_rate=0.999999)
                          .observe('B3', sample))
        with self.assertRaises(ValueError):
            sensing.SensorModel(dropout_rate=1.0)
        observed = sensing.SensorModel(seed=1, latency_ms=30).observe('B3', sample)
        self.assertEqual(observed['latency_ms'], 30)

    def test_estimator_converges_on_hover(self):
        estimator = sensing.AlphaBetaEstimator(alpha=0.4, beta=0.1, dt_s=0.1)
        for _ in range(30):
            pos, vel = estimator.update((2.0, 1.0, 1.5))
        self.assertLess(math.dist(pos, (2.0, 1.0, 1.5)), 0.05)
        self.assertLess(math.hypot(*vel[:2]), 0.05)

    def test_closure_report_shape(self):
        report = sensing.compare_truth_vs_sensed(
            sensing.synthetic_hover(duration_s=8.0), config=dict(seed=5))
        self.assertEqual(report['samples'], 80)
        self.assertIn('truth_hits', report)
        self.assertIn('sensed_hits', report)
        self.assertGreaterEqual(report['estimator']['samples'], 1)
        self.assertIn('scope', report)

    def test_controller_sees_estimate_not_truth(self):
        trace = sensing.synthetic_hover(duration_s=3.0, seed=2)
        adapter = sensing.OnboardFeedback(['B3'], dict(seed=2, sigma_xy=0.05))
        estimate = adapter.feed('B3', trace[0][1])
        self.assertTrue(estimate['sensed'])
        self.assertNotEqual(estimate['xyz'], trace[0][1]['xyz'])
        self.assertIn('estimate_error_m', estimate)


class TestMeasuredLink(unittest.TestCase):
    def test_profile_replays_deterministically(self):
        measurement = fake_measurement()
        p1 = MeasuredLinkProfile(measurement, 1000, seed=11)
        p2 = MeasuredLinkProfile(measurement, 1000, seed=11)
        ids = ['m1', 'm2', 'm3', 'm4']
        self.assertEqual([p1.offset_ms(i) for i in ids], [p2.offset_ms(i) for i in ids])
        self.assertEqual([p1.dropped(i) for i in ids], [p2.dropped(i) for i in ids])
        self.assertEqual(len(p1.to_dict()['measurement_sha256']), 64)

    def test_measured_network_drops_only_real_events(self):
        profile = MeasuredLinkProfile(fake_measurement(), 1000, seed=4)
        net = MeasuredNetwork(1000, lambda a, b: True, profile)
        poses = {'a': 'L', 'b': 'E'}
        for i in range(20):
            net.send('a', 'b', {}, 0, f'msg{i}', poses=poses)
        delivered = net.advance(1000 + profile.jitter_ms + 10, poses)
        self.assertLessEqual(len(delivered), 20)
        self.assertTrue(all(m.message_id not in net.dropped for m in delivered))
        self.assertTrue(all(isinstance(v, int) for v in net.offsets.values()))

    def test_profile_rejects_empty_measurement(self):
        with self.assertRaises(ValueError):
            MeasuredLinkProfile(dict(rows=[]), 1000)


class TestQuorumConsensus(unittest.TestCase):
    def test_full_connectivity_commits_with_majority(self):
        c = QuorumConsensus(('R1', 'R2', 'R3', 'B1', 'B2'))
        result = c.propose('E', 'R1', 1, 'R1')
        self.assertEqual(result['status'], 'COMMITTED')
        self.assertEqual(c.state('E'), ('R1', 1))
        self.assertEqual(result['messages'], 3 * len(c.members))

    def test_minority_partition_fails_closed(self):
        c = QuorumConsensus(('R1', 'R2', 'R3', 'B1', 'B2'))
        result = c.propose('E', 'R1', 1, 'R1', reachable={'R1', 'R2'})
        self.assertEqual(result['status'], 'NO_COMMIT_PROMISE')
        self.assertIsNone(c.state('E'))
        self.assertEqual(c.no_commit, 1)

    def test_stale_term_rejected(self):
        c = QuorumConsensus(('R1', 'R2', 'R3'))
        self.assertEqual(c.propose('E', 'R1', 5, 'R1')['status'], 'COMMITTED')
        self.assertEqual(c.propose('E', 'R2', 4, 'R2')['status'], 'REJECTED_STALE_TERM')
        self.assertEqual(c.state('E'), ('R1', 5))

    def test_audit_against_referee(self):
        c = QuorumConsensus(('R1', 'R2', 'R3'))
        c.propose('E', 'R1', 1, 'R1')
        audit = c.audit({'E': 'R1', 'W': 'R2'})
        self.assertEqual(audit['agree'], 1)
        self.assertEqual(audit['undecided'], 1)
        self.assertGreater(audit['total_messages'], 0)


if __name__ == '__main__':
    unittest.main()

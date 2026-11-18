import unittest
from gongyu.feedback_time import sample_time,aligned_sample


class FeedbackTime(unittest.TestCase):
    def test_stale_or_future_transform_is_not_freshened_by_odometry(self):
        self.assertIsNone(sample_time(1500,1000))
        self.assertIsNone(sample_time(1000,1001))
        self.assertEqual(sample_time(1100,1000),1000)

    def test_air_pose_uses_latest_past_sample_without_relabelling_future_frames(self):
        old={'t':1.0};future={'t':1.04}
        self.assertIs(aligned_sample([old,future],1.02),old)
        self.assertIsNone(aligned_sample([old,future],1.5))

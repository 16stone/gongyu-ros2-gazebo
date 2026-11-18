import math
import unittest

from gongyu.feedback import PositionController


def sample(t=0.,xyz=(0.,0.,0.),yaw=0.,speed=0.,wz=0.):
    return {'t':t,'xyz':xyz,'yaw':yaw,'speed':speed,'wz':wz}


class Feedback(unittest.TestCase):
    def test_air_world_target_is_rotated_to_body_velocity_and_bounded(self):
        c=PositionController('air');c.set_target((10.,0.,2.))
        vx,vy,vz,wz=c.command(sample(yaw=math.pi/2),0.)
        self.assertAlmostEqual(vx,0.,places=6)
        self.assertAlmostEqual(vy,-.5,places=6)
        self.assertAlmostEqual(vz,.4)
        self.assertEqual(wz,0.)

    def test_arrival_requires_one_second_of_low_speed_feedback(self):
        c=PositionController('air');c.set_target((1.,0.,2.))
        c.command(sample(0.,(1.,0.,2.),speed=.4),0.)
        self.assertEqual(c.state,'ACTIVE')
        c.command(sample(.1,(1.,0.,2.)),.1)
        c.command(sample(.9,(1.,0.,2.)),.9)
        self.assertEqual(c.state,'ACTIVE')
        c.command(sample(1.1,(1.,0.,2.)),1.1)
        self.assertEqual(c.state,'SUCCEEDED')

    def test_yaw_goal_cannot_succeed_before_turning(self):
        c=PositionController('air');c.set_target((0.,0.,0.),yaw=math.pi/2)
        for t in (0.,1.,2.):
            command=c.command(sample(t),t)
        self.assertGreater(command[3],0)
        self.assertEqual(c.state,'ACTIVE')

    def test_stale_feedback_cannot_confirm_arrival(self):
        c=PositionController('ground');c.set_target((0.,0.,0.))
        self.assertEqual(c.command(sample(),1.),(0.,0.,0.,0.))
        self.assertEqual(c.state,'FEEDBACK_LOST')

    def test_cancel_holds_actual_air_pose_without_success(self):
        c=PositionController('air');c.set_target((4.,0.,2.))
        s=sample(1.,(1.,0.,1.))
        c.cancel(s)
        self.assertEqual(c.command(s,1.),(0.,0.,0.,0.))
        self.assertEqual(c.state,'CANCELLED')

    def test_ground_turns_before_driving_toward_a_target_behind_it(self):
        c=PositionController('ground');c.set_target((-2.,0.,0.))
        vx,vy,vz,wz=c.command(sample(),0.)
        self.assertEqual(vx,0.)
        self.assertEqual((vy,vz),(0.,0.))
        self.assertGreater(abs(wz),0.)


if __name__=='__main__':
    unittest.main()

from concurrent.futures import Future
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

from rclpy.time import Time

from ros.ground_adapter import Nav2GroundAdapter


class GroundAdapter(TestCase):
    def setUp(self):
        self.node=Mock();self.node.get_clock.return_value.now.return_value=Time(seconds=1.)
        self.events=[];self.patch=patch('ros.ground_adapter.ActionClient');self.client=self.patch.start().return_value
        self.addCleanup(self.patch.stop)
        self.adapter=Nav2GroundAdapter(self.node,'B1',lambda kind,payload:self.events.append((kind,payload)))

    def accepted_goal(self):
        request=Future();self.client.send_goal_async.return_value=request
        result=Future();handle=Mock(accepted=True);handle.get_result_async.return_value=result
        self.adapter.submit(4.,2.,0.)
        request.set_result(handle)
        return handle,result

    def test_acceptance_is_not_navigation_success(self):
        handle,result=self.accepted_goal()
        self.assertEqual(self.adapter.state,'ACTIVE')
        result.set_result(SimpleNamespace(status=4,result=SimpleNamespace(error_code=0)))
        self.assertEqual(self.adapter.state,'SUCCEEDED_NAV2')

    def test_cancel_ack_does_not_replace_actual_terminal_result(self):
        handle,result=self.accepted_goal()
        cancel=Future();handle.cancel_goal_async.return_value=cancel
        self.adapter.cancel()
        cancel.set_result(SimpleNamespace(goals_canceling=[object()]))
        self.assertEqual(self.adapter.state,'CANCEL_REQUESTED')
        result.set_result(SimpleNamespace(status=5,result=SimpleNamespace(error_code=0)))
        self.assertEqual(self.adapter.state,'CANCELED')

    def test_delayed_feedback_from_previous_goal_cannot_change_new_goal(self):
        handle,result=self.accepted_goal()
        old_feedback=self.client.send_goal_async.call_args.kwargs['feedback_callback']
        result.set_result(SimpleNamespace(status=4,result=SimpleNamespace(error_code=0)))
        self.client.send_goal_async.return_value=Future()
        self.adapter.submit(0.,2.,0.)
        old_feedback(SimpleNamespace(feedback=SimpleNamespace(distance_remaining=0.,number_of_recoveries=0)))
        self.assertEqual(self.adapter.state,'REQUESTED')
        self.assertNotEqual(self.events[-1][0],'navigation_feedback')

    def test_continuous_poses_use_one_through_action_and_the_same_terminal_receipt(self):
        request=Future();self.client.send_goal_async.return_value=request
        targets=[(4.,0.,3.14159),(3.,0.,3.14159),(1.8,.95,1.36)]
        self.adapter.submit_path(targets)
        goal=self.client.send_goal_async.call_args.args[0]
        self.assertEqual(len(goal.poses),3);self.assertEqual(goal.poses[-1].pose.position.x,1.8)
        self.assertTrue(goal.behavior_tree.endswith('axial_transit.xml'))
        self.assertEqual(self.adapter.state,'REQUESTED')
        with self.assertRaises(RuntimeError):self.adapter.submit(1.,0.,0.)
        result=Future();handle=Mock(accepted=True);handle.get_result_async.return_value=result;request.set_result(handle)
        self.assertEqual(self.adapter.state,'ACTIVE');result.set_result(SimpleNamespace(status=4,result=SimpleNamespace(error_code=0)))
        self.assertEqual(self.adapter.state,'SUCCEEDED_NAV2')

    def test_bad_continuous_goals_do_not_claim_adapter_state(self):
        with self.assertRaises(ValueError):self.adapter.submit_path([(1.,0.,0.),(float('nan'),0.,0.)])
        self.assertEqual(self.adapter.state,'IDLE');self.client.send_goal_async.assert_not_called()

    def test_continuous_path_records_passive_plan_and_remaining_goal_count(self):
        request=Future();self.client.send_goal_async.return_value=request
        self.adapter.submit_path([(3.,0.,0.),(5.25,.95,1.3)])
        goal=self.client.send_goal_async.call_args.args[0]
        result=Future();handle=Mock(accepted=True);handle.get_result_async.return_value=result;request.set_result(handle)
        observed=SimpleNamespace(header=goal.poses[0].header,poses=goal.poses)
        self.adapter._plan(observed)
        self.assertEqual(self.events[-1][0],'navigation_plan_observed')
        self.assertEqual(self.events[-1][1]['points'][0],[3.,0.])
        callback=self.client.send_goal_async.call_args.kwargs['feedback_callback']
        callback(SimpleNamespace(feedback=SimpleNamespace(distance_remaining=2.,number_of_recoveries=0,number_of_poses_remaining=2)))
        self.assertEqual(self.events[-1][1]['remaining_poses'],2)
        result.set_result(SimpleNamespace(status=4,result=SimpleNamespace(error_code=0)))
        count=len(self.events);self.adapter._plan(observed);self.assertEqual(len(self.events),count)

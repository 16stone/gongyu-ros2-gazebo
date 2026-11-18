import unittest
from freeze_physical_m2 import physical_m2_card
from gongyu.run import simulate


class JointExternalService(unittest.TestCase):
    def test_external_first_report_can_combine_with_own_support_for_second_cargo(self):
        result=simulate(physical_m2_card(),'P3','joint_service_regression')
        self.assertTrue(any(e.kind=='slot_exchange_committed' for e in result.events))
        self.assertTrue(all(t['on_time'] for t in result.metrics['tasks'].values()))
        first=next(e for e in result.events if e.kind=='load_started' and e.task_id=='blue1')
        second=next(e for e in result.events if e.kind=='load_started' and e.task_id=='blue2')
        self.assertEqual(first.payload['report']['source_id'],'R5')
        self.assertEqual(second.payload['report']['source_id'],'B3')
        self.assertFalse(result.world.violations)
        decision=next(e for e in result.events if e.actor=='B1' and e.kind=='contract_decision')
        self.assertLessEqual(decision.payload['distinct_evaluated'],64)


if __name__=='__main__':unittest.main()

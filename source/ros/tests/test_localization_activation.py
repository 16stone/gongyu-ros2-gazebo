import unittest
from types import SimpleNamespace
from unittest.mock import patch
from ros.check_fleet_startup import activate_localization

class Localization(unittest.TestCase):
    def run_fake(self,late):
        clock=[0.];active=set();events=[];destroyed=[]
        actors=('B1','B2','R1','R2','R3','R4')
        def future(value):return SimpleNamespace(done=lambda:True,result=lambda:value)
        def client(typ,path):
            actor=path.split('/')[1];manager='manage_nodes' in path
            def call(request):
                if manager:active.add(actor);return future(SimpleNamespace(success=True))
                return future(SimpleNamespace(current_state=SimpleNamespace(id=3 if actor in active else 1)))
            return SimpleNamespace(service_is_ready=lambda:clock[0]>=late.get(actor,0),call_async=call)
        node=SimpleNamespace(create_client=client,destroy_client=lambda c:destroyed.append(c))
        def spin(*a,**kw):clock[0]+=1
        with patch('ros.check_fleet_startup.time.monotonic',side_effect=lambda:clock[0]),patch('ros.check_fleet_startup.rclpy.spin_once',side_effect=spin):
            result=activate_localization(node,actors,lambda *a:events.append(a),lambda:None)
        return result,clock[0],events,destroyed

    def test_six_actor_discovery_can_finish_after_legacy_ninety_seconds(self):
        result,elapsed,events,destroyed=self.run_fake({'R4':110})
        self.assertEqual(set(result),{'B1','B2','R1','R2','R3','R4'})
        self.assertGreater(elapsed,90);self.assertLess(elapsed,180)
        self.assertEqual(len(destroyed),12)

    def test_absent_service_still_has_a_bounded_timeout(self):
        with self.assertRaisesRegex(TimeoutError,'R4'):
            self.run_fake({'R4':float('inf')})


class LifecyclePressure(unittest.TestCase):
    def simulate(self,manager_ready=True):
        clock=[0.];active=set();pending={};queries=[];concurrent=[]
        actors=('B1','B2','R1','R2','R3','R4')
        def client(typ,path):
            actor=path.split('/')[1];manager='manage_nodes' in path
            def call(request):
                if manager:
                    pending[actor]=clock[0]+1.;concurrent.append(len(pending))
                    def done():return clock[0]>=pending[actor]
                    def result():pending.pop(actor);active.add(actor);return SimpleNamespace(success=True)
                    return SimpleNamespace(done=done,result=result)
                queries.append((actor,clock[0]));return SimpleNamespace(done=lambda:True,result=lambda:SimpleNamespace(current_state=SimpleNamespace(id=3 if actor in active else 1)))
            return SimpleNamespace(service_is_ready=lambda:manager_ready if manager else True,call_async=call)
        node=SimpleNamespace(create_client=client,destroy_client=lambda c:None)
        def spin(*a,**kw):clock[0]+=.1
        with patch('ros.check_fleet_startup.time.monotonic',side_effect=lambda:clock[0]),patch('ros.check_fleet_startup.rclpy.spin_once',side_effect=spin):
            try:result=activate_localization(node,actors,lambda *a:None,lambda:None)
            except TimeoutError:result=None
        return result,queries,concurrent,clock[0]

    def test_unavailable_manager_does_not_flood_state_service(self):
        result,queries,_,elapsed=self.simulate(False)
        self.assertIsNone(result);self.assertGreaterEqual(elapsed,180)
        for actor in ('B1','B2','R1','R2','R3','R4'):
            times=[t for a,t in queries if a==actor]
            self.assertLessEqual(len(times),361)
            self.assertTrue(all(b-a>=.49 for a,b in zip(times,times[1:])))

    def test_startup_is_serial_and_requires_each_active_reply(self):
        result,_,concurrent,_=self.simulate()
        self.assertEqual(set(result),{'B1','B2','R1','R2','R3','R4'})
        self.assertEqual(max(concurrent),1)

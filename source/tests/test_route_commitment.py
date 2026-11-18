"""Regression for an actual retained booking cancelled after a transient empty observation."""
import copy,unittest
from dataclasses import replace
from types import SimpleNamespace
import test_route_pressure_v3 as pressure
from gongyu.model import Message
from gongyu.modes import ModeRouteController

class BookingCommitment(unittest.TestCase):
    def setup_route(self):
        view=pressure.RoutePressureV3().view();m=copy.deepcopy(view.public_map)
        m['travel_time_ms']['L>D']=m['travel_time_ms']['D>L']=116667
        current=[replace(view,public_map=m)];sent=[]
        world=SimpleNamespace(now=120000,view=lambda actor:current[0],emit=lambda *args:None,send=lambda *args,**kwargs:sent.append((args,kwargs)))
        controller=ModeRouteController('R1',[],'adversarial');controller.route_before_actions(world)
        self.assertEqual(controller.route_choice,'channel')
        empty=Message('entrance','R1',{'kind':'entrance_observation','observed_at':121000,'waiting':[]},120000,'empty',arrived_at=121000)
        current[0]=replace(current[0],now_ms=121000,inbox=current[0].inbox+(empty,));world.now=121000
        return world,controller,current,sent
    def test_transient_empty_observation_does_not_cancel_an_existing_legal_route_commitment(self):
        world,c,view,sent=self.setup_route();c.route_before_actions(world)
        self.assertEqual(c.route_choice,'channel')
        self.assertIsNone(c.cancel_pending)
        self.assertFalse(sent)
    def test_changed_resource_revision_still_reopens_route_selection(self):
        world,c,view,sent=self.setup_route()
        booking={**view[0].reservations[0],'start':250000,'end':298000,'revision':1}
        view[0]=replace(view[0],reservations=(booking,));c.route_before_actions(world)
        self.assertEqual(c.route_choice,'rebook');self.assertIsNotNone(c.cancel_pending);self.assertTrue(sent)
    def test_unstarted_route_cannot_outlive_its_own_feasibility_while_waiting_at_L(self):
        for mode in ('independent','adversarial'):
            view=pressure.RoutePressureV3().view();m=copy.deepcopy(view.public_map)
            m['travel_time_ms']['L>D']=m['travel_time_ms']['D>L']=70000
            tasks=tuple({**t,'deadline_ms':200000} if t['id']=='red1' else t for t in view.own_tasks)
            current=[replace(view,node='L',reservations=(),public_map=m,own_tasks=tasks)]
            world=SimpleNamespace(now=120000,view=lambda actor:current[0],emit=lambda *args:None,send=lambda *args,**kwargs:None)
            c=ModeRouteController('R1',[],mode);c.route_before_actions(world)
            self.assertEqual(c.route_choice,'bypass')
            current[0]=replace(current[0],now_ms=140000);world.now=140000
            c.route_before_actions(world)
            self.assertIsNone(c.route_choice,'a blocked, unstarted route needs a fresh common quota check')

if __name__=='__main__':unittest.main()

import copy,unittest
from unittest.mock import Mock
from dataclasses import replace
from freeze_g2 import g2_card
from gongyu.contracts import utility
from gongyu.model import LocalView,Message
from gongyu.modes import MODES,ModeRouteController,with_target_mode
from gongyu.policies import controllers
from gongyu.red_routes import RedRouteController
from gongyu.world import World


class TargetModes(unittest.TestCase):
    def view(self,observed_at=5000):
        payload=dict(kind='entrance_observation',observed_at=observed_at,waiting=[dict(actor='B1',node='E',since_ms=3000)])
        msg=Message('entrance','R1',payload,observed_at,'seen',arrived_at=5000)
        return LocalView('R1',5000,'E',inbox=(msg,),inventory='red1',own_tasks=({'id':'red1','deadline_ms':15000,'completed_ms':None},),
            public_map=dict(service_ms=2000,ground_speed=1,message_delay_ms=1000,channel_gap_ms=2000,
                edges=[['E','W',6,'ground'],['W','D',2,'ground'],['E','L',1,'ground'],['L','D',20,'ground']],
                travel_time_ms={'E>W':6000,'W>D':2000},target_constraints=dict(move_budget_ms=20000,spent_move_ms=0,observation_max_age_ms=2000,on_time_required=True)))
    def rows(self):
        return [dict(id=kind,completed_ms=end,active_ms=active,utility=utility(end,15000,active)) for kind,end,active in [('channel',15000,10000),('bypass',13000,8000)]]
    def test_adversarial_uses_only_fresh_delivered_current_waiting_after_own_constraints(self):
        cs=ModeRouteController('R1',[],'adversarial');view=self.view()
        best,details=cs.choose_route(view,self.rows());self.assertEqual(best['id'],'channel');self.assertGreater(details['adversarial_proxy_ms'],0)
        for v in [replace(view,inbox=()),self.view(1000),replace(view,node='L')]:
            best,details=cs.choose_route(v,self.rows());self.assertEqual(best['id'],'bypass')
        short=replace(view,own_tasks=({'id':'red1','deadline_ms':14000,'completed_ms':None},))
        self.assertEqual(cs.choose_route(short,self.rows())[0]['id'],'bypass')
        budget=copy.deepcopy(view.public_map);budget['target_constraints']['move_budget_ms']=7000
        self.assertEqual(cs.choose_route(replace(view,public_map=budget),self.rows())[0]['id'],'bypass')
        later=self.rows();later[0]['completed_ms']=18000;later[0]['utility']=utility(18000,20000,10000)
        broad=replace(view,own_tasks=({'id':'red1','deadline_ms':20000,'completed_ms':None},))
        self.assertEqual(cs.choose_route(broad,later)[0]['id'],'bypass')
        booked=replace(broad,reservations=({'actor':'R1','start':8000,'end':14000,'direction':['E','W'],'used':False},))
        self.assertEqual(cs.choose_route(booked,later)[0]['id'],'channel')
        impossible=replace(view,own_tasks=({'id':'red1','deadline_ms':6000,'completed_ms':None},))
        self.assertIsNone(cs.choose_route(impossible,self.rows())[0])
    def test_independent_and_adversarial_share_the_declared_feasible_set(self):
        independent=ModeRouteController('R1',[],'independent')
        adversarial=ModeRouteController('R1',[],'adversarial')
        view=self.view()
        late=replace(view,own_tasks=({'id':'red1','deadline_ms':6000,'completed_ms':None},))
        for controller in (independent,adversarial):
            self.assertIsNone(controller.choose_route(late,self.rows())[0],
                'minimum own on-time quota is a common constraint, not an adversarial-only handicap')
        short=replace(view,own_tasks=({'id':'red1','deadline_ms':14000,'completed_ms':None},))
        for controller in (independent,adversarial):
            best,details=controller.choose_route(short,self.rows())
            self.assertEqual(best['id'],'bypass')
            self.assertEqual(details['feasible_candidate_ids'],['bypass'])

    def test_cancel_and_rebook_cannot_claim_the_retained_booking_pressure(self):
        view=replace(self.view(),reservations=({'actor':'R1','start':5000,'end':11000,'direction':['E','W'],'used':False},))
        rows=self.rows()+[dict(id='rebook',completed_ms=13000,active_ms=8000,utility=utility(13000,15000,8000))]
        best,details=ModeRouteController('R1',[],'adversarial').choose_route(view,rows)
        self.assertEqual(best['id'],'channel', 'cancelling the slot is not retained occupancy')
        self.assertGreater(details['adversarial_proxy_ms'],0)

    def test_local_view_exposes_only_own_declared_on_time_quota(self):
        for mode in ('independent','adversarial'):
            w=World(with_target_mode(g2_card(),mode),'quota_'+mode)
            self.assertTrue(w.view('R1').public_map['target_constraints'].get('on_time_required',False))
            self.assertTrue(w.view('R2').public_map['target_constraints'].get('on_time_required',False))
            self.assertFalse(w.view('R3').public_map['target_constraints'].get('on_time_required',False))

    def test_observations_arrive_through_network_and_do_not_reveal_private_tasks(self):
        card=with_target_mode(g2_card(),'adversarial');w=World(card,'observations');w.poses['B1']='E'
        w.advance(0);self.assertFalse(any(m.payload.get('kind')=='entrance_observation' for m in w.view('R1').inbox if isinstance(m.payload,dict)))
        w.advance(1000);w.advance(2000);messages=[m for m in w.view('R1').inbox if isinstance(m.payload,dict) and m.payload.get('kind')=='entrance_observation']
        self.assertTrue(messages);p=messages[-1].payload;self.assertEqual(set(p),{'kind','observed_at','waiting'})
        self.assertEqual(set(p['waiting'][0]),{'actor','node','since_ms'})
        self.assertGreater(messages[0].arrived_at,messages[0].queued_at)
    def test_declared_staging_sensor_reports_presence_without_private_task_data(self):
        for staging_enabled in (False,True):
            card=with_target_mode(g2_card(),'adversarial')
            if staging_enabled:card['target_constraints']['observation_nodes']=['E','L']
            w=World(card,'staging_sensor');w.poses['B1']='L'
            for t in (0,1000,2000):w.advance(t)
            messages=[m.payload for m in w.view('R1').inbox
                if m.sender=='entrance' and isinstance(m.payload,dict) and m.payload.get('kind')=='entrance_observation']
            self.assertTrue(messages)
            blue=[p for p in messages[-1]['waiting'] if p['actor']=='B1']
            self.assertEqual(bool(blue),staging_enabled)
            if blue:self.assertEqual(set(blue[0]),{'actor','node','since_ms'})

    def test_all_modes_have_identical_tasks_and_budgets_but_distinct_responses(self):
        base=g2_card();cards=[with_target_mode(base,mode) for mode in MODES]
        for c in cards:
            self.assertEqual(c['tasks'],base['tasks']);self.assertEqual(c['fleet'],base['fleet'])
            self.assertEqual(c['target_constraints']['movement_budget_ms'],cards[0]['target_constraints']['movement_budget_ms'])
        for card in cards:
            cs=controllers(card,'P3');mode=card['target_mode']
            self.assertEqual(cs['R5'].cross_team_enabled,mode=='reciprocal')
            if mode=='reciprocal':
                self.assertIsInstance(cs['R2'],RedRouteController)
                self.assertTrue(cs['R2'].autonomous)
            if mode!='reciprocal':
                self.assertIsInstance(cs['R1'],ModeRouteController)
                self.assertEqual(cs['R1'].autonomous,mode!='nonresponsive')
    def test_disabled_cross_team_service_is_ignored_before_any_own_task_query(self):
        cs=controllers(with_target_mode(g2_card(),'independent'),'P3');w=Mock()
        w.view.side_effect=AssertionError('disabled service queried own tasks')
        cs['R5'].on_message(w,Message('R1','R5',dict(kind='m2_service',contract_id='disabled'),0,'service'))
        w.send.assert_not_called();w.emit.assert_not_called()
    def test_movement_budget_is_enforced_before_requesting_motion(self):
        card=with_target_mode(g2_card(),'adversarial');card['target_constraints']['movement_budget_ms']['R3']=11000
        w=World(card,'budget');self.assertFalse(w.start_move('R3','PN'));self.assertEqual(w.poses['R3'],'N0')
        self.assertNotIn('R3',w.busy);self.assertTrue(any(e.kind=='target_movement_budget_exhausted' for e in w.events))
    def test_autonomous_route_does_not_erase_own_release_gate(self):
        card=with_target_mode(g2_card(),'independent')
        next(t for t in card['tasks'] if t['id']=='red2')['release_ms']=8000
        w=World(card,'release');cs=controllers(card,'P3');w.advance(1000);cs['R2'].step(w)
        self.assertNotIn('R2',w.busy);self.assertEqual(w.poses['R2'],'E')
        self.assertFalse(w.start_move('R2','W'))


if __name__=='__main__':unittest.main()

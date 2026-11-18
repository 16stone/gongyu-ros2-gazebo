import unittest

from gongyu.contracts import ContractPeer,SlotExchange,utility
from gongyu.model import LocalView,Message
from gongyu.c1 import simulate


class Contracts(unittest.TestCase):
    def test_actual_report_must_satisfy_stricter_contract_terms(self):
        from unittest.mock import patch
        original=ContractPeer.request
        for terms in ({'minimum_quality':2.},{'maximum_age_ms':500}):
            with self.subTest(terms=terms):
                def request(peer):
                    rows=original(peer)
                    rows[0][1].update(terms)
                    return rows
                with patch.object(ContractPeer,'request',request):
                    r=simulate()
                self.assertNotEqual(r['contracts']['B1'],'FULFILLED')
                self.assertNotEqual(r['contracts']['R1'],'FULFILLED')

    def test_blue_rejects_a_quote_that_weakens_requested_quality(self):
        p=ContractPeer('B1');request=p.request()[0][1]
        quote={**request,'minimum_quality':.5,'accept_by_ms':8000}
        message=Message('R1','B1',{'kind':'offer','contract_id':'C1_exchange','quote':quote},0,'bad_quality')
        p.step(LocalView('B1',2000,'L',inbox=(message,),own_tasks=({'deadline_ms':39000},)))
        self.assertEqual(p.state,'REJECTED')

    def test_utility_keeps_legal_unassisted_release_candidate(self):
        baseline=utility(30000,39000,28000)
        release=utility(38000,39000,28000)
        trade=utility(38000,39000,14000)
        self.assertGreater(baseline,release)
        self.assertGreater(trade,baseline)

    def test_exchange_requires_both_owners_and_is_idempotent(self):
        slots=SlotExchange({'early':'B1','late':'R1'})
        quote={'contract_id':'c1','accept_by_ms':8000,'slots':['early','late'],'parties':['B1','R1']}
        self.assertFalse(slots.confirm('B1',quote,3000))
        self.assertEqual(slots.owners,{'early':'B1','late':'R1'})
        self.assertTrue(slots.confirm('R1',quote,4000))
        self.assertTrue(slots.confirm('R1',quote,5000))
        self.assertEqual(slots.owners,{'early':'R1','late':'B1'})
        self.assertEqual(slots.commits,1)
        with self.assertRaises(ValueError):
            slots.confirm('outsider',quote,5000)

    def test_late_confirmation_cannot_change_ownership(self):
        slots=SlotExchange({'early':'B1','late':'R1'})
        quote={'contract_id':'c1','accept_by_ms':8000,'slots':['early','late'],'parties':['B1','R1']}
        self.assertFalse(slots.confirm('B1',quote,3000))
        self.assertFalse(slots.confirm('R1',quote,9000))
        self.assertEqual(slots.commits,0)

    def test_expired_exchange_does_not_block_the_next_contract(self):
        slots=SlotExchange({'early':'B1','late':'R1'})
        old={'contract_id':'old','accept_by_ms':8000,'slots':['early','late'],'parties':['B1','R1']}
        self.assertFalse(slots.confirm('B1',old,3000))
        new={**old,'contract_id':'new','accept_by_ms':16000}
        self.assertFalse(slots.confirm('B1',new,9000))
        self.assertTrue(slots.confirm('R1',new,10000))

    def test_c1_mutual_benefit_is_executed_not_only_predicted(self):
        r=simulate()
        self.assertEqual(r['completed'],{'red_inspect':15000,'red':30000,'blue':38000})
        self.assertEqual(r['active_ms']['B1'],14000)
        self.assertEqual(r['waiting_ms']['B1'],24000)
        self.assertEqual(r['contracts']['B1'],'FULFILLED')
        self.assertEqual(r['contracts']['R1'],'FULFILLED')
        self.assertEqual(r['slot_commits'],1)
        loads=[e for e in r['events'] if e.kind=='load_started']
        self.assertEqual(loads[0].t_ms,9000)
        self.assertEqual(loads[0].payload['report_age_ms'],1000)
        self.assertFalse(r['violations'])

    def test_c1_refusal_retains_independent_tasks(self):
        r=simulate(air_deadline_ms=14000)
        self.assertEqual(r['contracts']['R1'],'REJECTED')
        self.assertEqual(r['completed']['red_inspect'],12000)
        self.assertEqual(r['completed']['blue'],30000)
        self.assertEqual(r['completed']['red'],38000)
        self.assertEqual(r['slot_commits'],0)

    def test_c1_late_offer_boundary_never_commits(self):
        r=simulate(delay_ms=3000)
        self.assertEqual(r['contracts']['R1'],'EXPIRED')
        self.assertEqual(r['slot_commits'],0)
        self.assertTrue(any(e.kind=='contract_expired' for e in r['events']))
        self.assertFalse(r['violations'])

    def test_no_service_baseline(self):
        r=simulate(service=False)
        self.assertEqual(r['completed'],{'red_inspect':12000,'blue':30000,'red':38000})
        self.assertEqual(r['active_ms']['B1'],28000)
        self.assertEqual(r['waiting_ms']['B1'],2000)


if __name__=='__main__':
    unittest.main()

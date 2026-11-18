import itertools,json,math,tempfile,unittest
import xml.etree.ElementTree as E
from pathlib import Path
import yaml
from freeze_g2 import g2_card
from freeze_physical_m2 import physical_m2_card
from gongyu.berths import Berths
from ros import fleet_episode
from ros.audit_fleet_episode import audit
from ros.prepare_mission_world import prepare


class EightPlatformScene(unittest.TestCase):
    def test_eight_models_and_six_independent_navigation_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);card=g2_card();prepare(root,card)
            fleet=json.loads((root/'config/fleet.json').read_text())
            self.assertEqual(len(fleet),8);self.assertEqual(sum(a['mode']=='ground' for a in fleet),6)
            world=E.parse(root/'worlds/fleet.sdf').getroot().find('world')
            bridge=yaml.safe_load((root/'config/fleet_bridge.yaml').read_text())
            for actor in ('B1','B2','R1','R2','R3','R4'):
                self.assertIsNotNone(world.find(f'model[@name="{actor}"]'))
                cfg=yaml.safe_load((root/f'config/nav2_{actor}.yaml').read_text())
                self.assertEqual(cfg[actor]['amcl']['ros__parameters']['base_frame_id'],actor+'/base_footprint')
                self.assertTrue(any(r['ros_topic_name']==f'/{actor}/peer_scan' for r in bridge))
            initial=[r['initial_xyz'] for r in fleet if r['mode']=='ground']
            self.assertEqual(len(set(tuple(p) for p in initial)),6)
            for a,b in itertools.combinations(initial,2):self.assertGreater(math.dist(a[:2],b[:2]),.64)

    def test_only_the_supported_six_or_eight_fleets_pass_identity_validation(self):
        for card,counts in ((physical_m2_card(),(4,2)),(g2_card(),(6,2))):
            ground,air=fleet_episode.fleet_actors(card);self.assertEqual((len(ground),len(air)),counts)
        card=g2_card();del card['fleet']['R4']
        with self.assertRaises(ValueError):fleet_episode.fleet_actors(card)
        card=g2_card();card['fleet']['unknown']={'mode':'other'}
        with self.assertRaises(ValueError):fleet_episode.fleet_actors(card)
        card=g2_card();card['fleet']['R9']=card['fleet'].pop('R4')
        with self.assertRaises(ValueError):fleet_episode.fleet_actors(card)
        card=g2_card();card['fleet']['B1']['mode']='air';card['fleet']['B3']['mode']='ground'
        with self.assertRaises(ValueError):fleet_episode.fleet_actors(card)

    def test_audit_checks_all_configured_identities_not_a_literal_six(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);scene=root/'scene';scene.mkdir();out=root/'out';out.mkdir();card=g2_card()
            (scene/'scenario.json').write_text(json.dumps(card))
            (out/'metrics.json').write_text(json.dumps(dict(mission=dict(tasks={},constraint_violations=[]),origin_ms=0,status='FIXTURE',ended='full_window')))
            berths=Berths(card)
            (out/'feedback.jsonl').write_text(''.join(json.dumps({'actor':a})+'\n' for a in card['fleet']))
            (out/'independent_truth.jsonl').write_text(''.join(json.dumps(dict(actor=a,t_s=0,xyz=berths.position(a,s['node'])))+'\n' for a,s in card['fleet'].items()))
            ready=dict(kind='physical_all_ready',actor='referee',t_ms=0,payload=dict(actors=list(card['fleet'])))
            (out/'events.jsonl').write_text(json.dumps(ready)+'\n');audit(out,scene)
            ready['payload']['actors'].remove('R4');(out/'events.jsonl').write_text(json.dumps(ready)+'\n')
            with self.assertRaises(AssertionError):audit(out,scene)


if __name__=='__main__':unittest.main()

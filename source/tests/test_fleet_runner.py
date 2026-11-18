import json,os,signal,subprocess,sys,tempfile,time,unittest
import ros.fleet_runner as runner
from pathlib import Path
from unittest.mock import patch
from ros.fleet_runner import environment_for,update_progress,stop_owned

class FleetRunner(unittest.TestCase):
    def test_local_transport_does_not_inherit_foreign_discovery_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ,{'ROS_STATIC_PEERS':'192.0.2.1','ROS_AUTOMATIC_DISCOVERY_RANGE':'SUBNET','GONGYU_ACTIVE_GROUND':'B1'}):
                env=environment_for(Path(temp),Path(temp)/'new_run')
            self.assertEqual(env['ROS_AUTOMATIC_DISCOVERY_RANGE'],'LOCALHOST')
            self.assertEqual(env['ROS_DOMAIN_ID'],'83')
            self.assertNotIn('ROS_STATIC_PEERS',env)
            self.assertNotIn('GONGYU_ACTIVE_GROUND',env)
            import xml.etree.ElementTree as ET
            root=ET.fromstring(env['CYCLONEDDS_URI'])
            interface=root.find('.//{*}NetworkInterface')
            self.assertEqual(interface.attrib['name'],'lo')
            self.assertEqual(root.find('.//{*}AllowMulticast').text,'false')
            self.assertEqual(root.findtext('.//{*}MaxMessageSize'),'1400B')
            self.assertEqual(root.findtext('.//{*}FragmentSize'),'1100B')
    def test_existing_evidence_directory_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileExistsError):environment_for(Path(temp),Path(temp))
    def test_stalled_mission_is_reported_without_treating_a_waiting_task_as_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            self.assertEqual(update_progress(out,None,0.,20.),(None,0.))
            (out/'checkpoint.json').write_text(json.dumps({'mission_ms':10000}))
            self.assertEqual(update_progress(out,None,0.,20.),(10000,20.))
            self.assertEqual(update_progress(out,10000,20.,30.),(10000,20.))
            with self.assertRaises(TimeoutError):update_progress(out,10000,20.,111.)
            (out/'checkpoint.json').write_text(json.dumps({'mission_ms':20000}))
            self.assertEqual(update_progress(out,10000,20.,111.),(20000,111.))
    @unittest.skipUnless(os.name=='posix','Linux process groups')
    def test_cleanup_stops_only_the_group_created_for_this_run(self):
        process=subprocess.Popen(['sleep','60'],start_new_session=True)
        try:
            receipt=stop_owned(process)
            self.assertEqual(receipt['pgid'],process.pid)
            self.assertIsNotNone(process.poll())
            self.assertEqual(os.getpgrp(),os.getpgid(os.getpid()))
        finally:
            if process.poll() is None:process.kill();process.wait()


class RunnerReviewRegressions(unittest.TestCase):
    def test_source_archive_without_git_records_its_actual_code_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'gongyu').mkdir();(root/'gongyu/model.py').write_text('VALUE=1\n')
            info=runner.source_fingerprint(root)
            self.assertEqual(info['revision'],'unknown')
            self.assertEqual(len(info['sha256']['gongyu/model.py']),64)
    def test_foreign_stack_is_refused_but_an_unrelated_domain_is_allowed(self):
        self.assertTrue(runner.is_fleet_process(['ros2','launch','/tmp/ros/fleet.launch.py'],{}))
        self.assertTrue(runner.is_fleet_process(['/opt/ros/jazzy/lib/nav2_controller/controller_server'],{'ROS_DOMAIN_ID':'83'}))
        self.assertTrue(runner.is_fleet_process(['gz','sim','-s'],{'GZ_PARTITION':'gongyu_fleet_episode_20261030'}))
        self.assertFalse(runner.is_fleet_process(['/opt/ros/jazzy/lib/demo_nodes_cpp/talker'],{'ROS_DOMAIN_ID':'82'}))
    def test_wall_cadenced_clock_progress_survives_slow_simulation(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);(out/'checkpoint.json').write_text(json.dumps({'mission_ms':10000}))
            (out/'runtime_heartbeat.json').write_text(json.dumps({'mission_ms':10001}))
            self.assertEqual(update_progress(out,10000,20.,111.),(10001,111.))
    def test_driver_and_mission_capture_events_are_both_tailed_without_losing_partial_lines(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);mission={'actor':'R1','kind':'red_route_decision','payload':{},'t_ms':120000}
            driver={'actor':'R1','kind':'physical_arrival_granted','payload':{'goal_id':1},'wall':123.}
            (out/'events.jsonl').write_text(json.dumps(mission)+'\n')
            (out/'driver_events.jsonl').write_text(json.dumps(driver))
            offsets={};first=list(runner.capture_updates(out,offsets))
            self.assertEqual(first,[('events.jsonl',mission)])
            with (out/'driver_events.jsonl').open('a') as f:f.write('\n')
            second=list(runner.capture_updates(out,offsets))
            self.assertEqual(second,[('driver_events.jsonl',driver)])
    @unittest.skipUnless(os.name=='posix','Linux signals and process groups')
    def test_sigterm_reaches_cleanup_and_saves_a_shutdown_receipt(self):
        from freeze_m2 import m2_card
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);scene=root/'scene';(scene/'worlds').mkdir(parents=True);(scene/'config').mkdir()
            (scene/'scenario.json').write_text(json.dumps(m2_card()))
            for rel in ['worlds/fleet.sdf','config/fleet.json','config/fleet_bridge.yaml']:(scene/rel).write_text('fixture')
            out=root/'episode';launch=root/'episode_launch'
            code="import subprocess,sys;import ros.fleet_runner as r;original=subprocess.Popen;r.subprocess.Popen=lambda command,**kw:original([sys.executable,'-c','import time;time.sleep(60)'] if command[0]=='ros2' or len(command)>2 and command[1]=='-m' else command,**kw);r.main(sys.argv[1],sys.argv[2],'P3')"
            worker=subprocess.Popen([sys.executable,'-c',code,str(scene),str(out)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            pids=[]
            try:
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    p=launch/'live_run.json'
                    if p.exists():
                        data=json.loads(p.read_text());pids=[data[k] for k in ['stack_pid','client_pid','capture_pid'] if k in data]
                        if len(pids)==3:break
                    if worker.poll() is not None:break
                    time.sleep(.05)
                self.assertEqual(len(pids),3)
                worker.send_signal(signal.SIGTERM);worker.wait(timeout=10)
                self.assertTrue((launch/'shutdown.json').exists(),'SIGTERM must not bypass finally')
                for pid in pids:self.assertEqual(runner.live_owned_members(pid),[])
            finally:
                if worker.poll() is None:worker.kill();worker.wait()
                for pid in pids:
                    if runner.live_owned_members(pid):
                        try:os.killpg(pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                if runner.live_owned_members(worker.pid):
                    os.killpg(worker.pid,signal.SIGKILL)
                worker.communicate(timeout=2)

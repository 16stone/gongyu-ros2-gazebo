import json,os,signal,threading,unittest
from pathlib import Path
import tempfile
import rclpy
from rclpy.context import Context
from rclpy.signals import SignalHandlerOptions
from ros.fleet_episode import stop_for_shutdown,save_checkpoint,check_interrupt


class EpisodeShutdown(unittest.TestCase):
    def test_checkpoint_preserves_each_new_record_once_before_cleanup(self):
        from types import SimpleNamespace
        world=SimpleNamespace(now=10000,metrics=lambda:dict(tasks={'blue1':dict(completed_ms=None)}))
        streams={'feedback':[dict(actor='B1',t=1)],'events':[dict(kind='started')]};offsets={}
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);save_checkpoint(out,world,streams,offsets)
            streams['feedback'].append(dict(actor='B1',t=2));save_checkpoint(out,world,streams,offsets)
            self.assertEqual(len((out/'feedback.jsonl').read_text().splitlines()),2)
            self.assertEqual(len((out/'events.jsonl').read_text().splitlines()),1)
            snapshot=json.loads((out/'checkpoint.json').read_text())
            self.assertEqual(snapshot['status'],'PARTIAL_NOT_FINAL');self.assertEqual(snapshot['mission_ms'],10000)

    def test_one_invalid_publisher_cannot_skip_other_stops_or_evidence(self):
        calls=[];events=[]
        class Ground:
            def __init__(self,name):self.name=name
            def cancel(self):
                calls.append(self.name)
                if self.name=='B1':raise RuntimeError('invalid ROS context')
        def publish(a,command):
            calls.append(a)
            if a=='B3':raise RuntimeError('invalid publisher context')
        errors=stop_for_shutdown({'B1':Ground('B1'),'R1':Ground('R1')},['B3','R5'],publish,lambda *args:events.append(args))
        self.assertEqual(calls,['B1','R1','B3','R5'])
        self.assertEqual(len(errors),2);self.assertEqual(len(events),2)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'evidence.json';path.write_text(str(errors));self.assertTrue(path.read_text())

    def test_python_interrupt_keeps_explicit_ros_context_valid_for_cleanup(self):
        previous=signal.getsignal(signal.SIGINT);context=Context();requested=threading.Event()
        signal.signal(signal.SIGINT,lambda *_:requested.set())
        try:
            rclpy.init(context=context,signal_handler_options=SignalHandlerOptions.NO)
            os.kill(os.getpid(),signal.SIGINT)
            self.assertTrue(requested.is_set())
            with self.assertRaises(KeyboardInterrupt):check_interrupt(requested)
            self.assertTrue(context.ok())
        finally:
            if context.ok():rclpy.shutdown(context=context)
            signal.signal(signal.SIGINT,previous)

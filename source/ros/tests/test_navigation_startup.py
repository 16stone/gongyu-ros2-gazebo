import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
from geometry_msgs.msg import PoseWithCovarianceStamped
from ros import check_fleet_startup as startup


class NavigationStartup(unittest.TestCase):
    def test_starts_serially_and_confirms_actual_active_components(self):
        node=Mock();callbacks=[];ticks=[0];pending=[];started=[];queries={}
        node.create_subscription.side_effect=lambda kind,name,cb,qos:callbacks.append((name,cb)) or Mock()
        publisher=Mock();publisher.get_subscription_count.return_value=1;node.create_publisher.return_value=publisher
        def create(kind,name):
            client=Mock();client.service_is_ready.return_value=True;actor=name.split('/')[1]
            def call(request):
                if name.endswith('/get_state'):
                    queries[name]=queries.get(name,0)+1
                    value=NS(current_state=NS(id=3 if actor in started and ticks[0]>=dict(pending)[actor]+2 else 1))
                    return NS(done=lambda:True,result=lambda:value)
                self.assertFalse(any(ticks[0]<t+2 for _,t in pending),'concurrent navigation startups')
                started.append(actor);pending.append((actor,ticks[0]))
                return NS(done=lambda:ticks[0]>=dict(pending)[actor]+2,result=lambda:NS(success=True))
            client.call_async.side_effect=call;return client
        node.create_client.side_effect=create
        def spin(*args,**kwargs):
            ticks[0]+=1
            for name,cb in callbacks:
                if name.endswith('/amcl_pose'):cb(PoseWithCovarianceStamped())
        with tempfile.TemporaryDirectory() as temp:
            scene=Path(temp)/'scene';(scene/'config').mkdir(parents=True)
            (scene/'config/fleet.json').write_text(json.dumps([dict(id=a,initial_xyz=[0,0,0]) for a in ('R3','R4')]))
            with patch.object(startup.rclpy,'spin_once',side_effect=spin),patch('tf2_ros.Buffer') as buffer,patch('rclpy.action.ActionClient') as action:
                buffer.return_value.can_transform.return_value=True;action.return_value.server_is_ready.return_value=True
                result=startup.check_localized_navigation(node,['R3','R4'],scene,{a+'/scan':dict(stamp_s=0) for a in ('R3','R4')})
        self.assertEqual(started,['R3','R4'])
        self.assertTrue(all(v['navigation_started'] for v in result.values()))
        self.assertTrue(all(n>=2 for n in queries.values()),'manager reply needs fresh actual lifecycle confirmation')


if __name__=='__main__':unittest.main()

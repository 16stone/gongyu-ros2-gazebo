import itertools,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from ros import check_fleet_startup as startup


def future(value):
    return SimpleNamespace(done=lambda:True,result=lambda:value)


class LocalizationStartup(unittest.TestCase):
    def node(self,states):
        node=Mock();clients={}
        def create(kind,name):
            client=Mock();client.service_is_ready.return_value=True
            if name.endswith('/get_state'):
                client.call_async.side_effect=[future(SimpleNamespace(current_state=SimpleNamespace(id=i))) for i in states]
            else:client.call_async.return_value=future(SimpleNamespace(success=True))
            clients[name]=client;return client
        node.create_client.side_effect=create;return node,clients

    def test_inactive_state_requires_start_response_and_actual_active_confirmation(self):
        node,clients=self.node([1,3]);events=[]
        with patch.object(startup.rclpy,'spin_once'):
            result=startup.activate_localization(node,['B2'],lambda *args:events.append(args),lambda:None)
        self.assertEqual(result,{'B2':3})
        self.assertEqual(clients['/B2/amcl/get_state'].call_async.call_count,2)
        self.assertEqual(clients['/B2/lifecycle_manager_localization/manage_nodes'].call_async.call_count,1)
        self.assertEqual(node.destroy_client.call_count,2)

    def test_active_component_is_not_started_again(self):
        node,clients=self.node([3])
        with patch.object(startup.rclpy,'spin_once'):startup.activate_localization(node,['B1'],lambda *args:None,lambda:None)
        clients['/B1/lifecycle_manager_localization/manage_nodes'].call_async.assert_not_called()

    def test_unreceived_reply_times_out_without_false_activation_and_destroys_clients(self):
        node,clients=self.node([1])
        original=node.create_client.side_effect
        def create(kind,name):
            client=original(kind,name)
            if not name.endswith('/get_state'):
                client.call_async.return_value=SimpleNamespace(done=lambda:False)
            return client
        node.create_client.side_effect=create
        with patch.object(startup.rclpy,'spin_once'),patch.object(startup.time,'monotonic',side_effect=itertools.count(0,10)):
            with self.assertRaises(TimeoutError):startup.activate_localization(node,['B2'],lambda *args:None,lambda:None)
        self.assertEqual(node.destroy_client.call_count,2)


if __name__=='__main__':unittest.main()

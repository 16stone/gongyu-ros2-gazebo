import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from ros import fleet_episode


class FailureScene(unittest.TestCase):
    def test_last_scan_preserves_actual_frame_angles_and_invalid_returns(self):
        message=SimpleNamespace(header=SimpleNamespace(frame_id='R2/base_scan',stamp=SimpleNamespace(sec=10,nanosec=2000000)),
            angle_min=-1.,angle_increment=.1,range_min=.1,range_max=10.,ranges=[.4,float('inf'),float('nan')])
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp);fleet_episode.save_last_scans(out,{'R2/scan':message})
            row=json.loads((out/'last_scans.json').read_text())['R2/scan']
            self.assertEqual(row['ranges'],[.4,None,None]);self.assertEqual(row['stamp_s'],10.002)
            self.assertEqual(row['frame_id'],'R2/base_scan')

    def test_missing_failure_screenshot_does_not_discard_original_error(self):
        events=[]
        def capture(label):raise RuntimeError('GUI unavailable')
        fleet_episode.capture_failure_scene(capture,lambda *args:events.append(args))
        self.assertEqual(events[0][1],'failure_screenshot_unavailable')


if __name__=='__main__':unittest.main()
